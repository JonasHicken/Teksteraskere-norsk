"""Fast start in app mode (Windows): Teksting's own window opens at once with a loading screen,
while the server code loads beside it. Before, these ran one after the other (~2 s each).

server.py hands over here before importing anything heavy; the server itself is then imported as the
module `server` in a background thread. The loading page (static/loading.html) switches to the app
by itself as soon as the server answers.
"""
import json
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

APP_ID = "Teksting.Teksting"  # same ID on the shortcuts (lag-snarveier.ps1) -> one taskbar button, pinnable
APP_DIR = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("TEKSTING_DATA", APP_DIR / "data"))
PORT = int(os.environ.get("TEKSTING_PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}/"


def _port_in_use():
    with socket.socket() as s:
        s.settimeout(0.3)  # on Windows a closed port takes ~2 s to fail; a local server answers at once
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def _show_existing():
    """Teksting already running? Bring its window forward (POST /api/show) instead of starting again."""
    if not _port_in_use():
        return False
    try:
        import urllib.request  # only needed when another Teksting is running
        req = urllib.request.Request(URL + "api/show", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=3) as r:
            return bool(json.load(r).get("ok"))
    except Exception:
        return False


def _ui_lang():
    try:
        return json.loads((DATA / "settings.json").read_text(encoding="utf-8")).get("ui_lang", "")
    except (OSError, ValueError):
        return ""


def loading_html():
    html = (APP_DIR / "static" / "loading.html").read_text(encoding="utf-8")
    return html.replace("__URL__", URL).replace("__LANG__", _ui_lang())


def main(t0, early=None):
    """early = (first, splash, dark) from tekst.splash.early(), which server.py runs before any other import."""
    if sys.stdout is None or "pythonw" in Path(sys.executable).name.lower():
        DATA.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(DATA / "teksting.log", "a", encoding="utf-8", buffering=1)
    print("\n---", time.strftime("%Y-%m-%d %H:%M:%S"), "starting")
    from tekst import splash as splash_mod
    first, splash, dark = early or splash_mod.early()
    if not first:
        # Teksting is already running (it holds the mutex): bring its window forward. If it is still starting,
        # its server may not answer yet, so keep trying. If it is closing (the icon was clicked again right
        # after closing: the old copy needs ~2.4 s to exit), its mutex comes to us when it is gone: start then.
        for _ in range(40):
            if _show_existing():
                os._exit(0)
            if splash_mod.own_mutex(500):
                print("  the previous Teksting had closed: starting")
                splash = splash_mod.make_splash(dark)
                break
        else:
            os._exit(0)
    if splash and splash.hwnd:
        print(f"  stand-in window after {time.time() - t0:.1f} s")
    # No port checks here: each costs ~0.3 s when nothing answers (it did twice per start before). If something
    # else holds the port, the loading screen simply shows whatever answers there.
    viewer = False

    srv = {}
    failed = threading.Event()

    def boot():
        try:
            import server
            server.T0 = t0
            srv["m"] = server
            server.serve_in_background()
            server.wait_until_ready()
            print(f"  server ready after {time.time() - t0:.1f} s")
        except Exception:
            traceback.print_exc()
            failed.set()

    if not viewer:
        threading.Thread(target=boot, daemon=True).start()

    try:
        import webview
    except Exception as e:  # no pywebview/.NET: use a browser window like before
        print("Own window not available, using a browser:", e)
        if splash:
            splash.close()
        _browser_fallback(srv, failed, viewer)
        return

    webview.settings["ALLOW_DOWNLOADS"] = True  # "Last ned SRT" opens a save dialog
    if os.environ.get("TEKSTING_DEBUG_PORT"):  # dev: inspect the window with Chrome DevTools
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ["TEKSTING_DEBUG_PORT"])
    # exactly where the stand-in window is (1440 x 900, or less on a small screen, centred)
    lx, ly, lw, lh = (splash and splash.logical) or splash_mod.layout()[0]
    w = webview.create_window("Teksting", html=loading_html(), x=lx, y=ly, width=lw, height=lh, min_size=(400, 500),
                              background_color="#10171d" if dark else "#edf1f4")  # --paper

    closing = {"flushed": False}

    def on_closing():
        if closing["flushed"]:
            return  # second round, after the flush below: close now
        # Closing while a video is transcribing hides the window; the job finishes, then the app quits.
        server = srv.get("m")
        if server and server.busy():
            server.WIN["hidden"] = True
            threading.Timer(0.05, w.hide).start()
            return False
        # The editor saves 0.8 s after the last key: closing sooner lost that edit (measured 2026-10-24).
        # Keep the window until the page has saved (at most 3 s), then close.
        threading.Thread(target=flush_then_close, daemon=True).start()
        return False

    def flush_then_close():
        done = threading.Event()

        def ask_page():
            try:  # evaluate_js waits (up to 20 s) for a page that is still loading: never let that hold the close
                w.evaluate_js("Promise.resolve(window.tekstingFlush ? window.tekstingFlush() : 1)", lambda _: done.set())
            except Exception as e:
                print("  flush before close failed:", e)
                done.set()

        threading.Thread(target=ask_page, daemon=True).start()
        done.wait(3)
        closing["flushed"] = True
        if "m" in srv:
            srv["m"].WIN["w"] = None  # closing: a new start must not "bring forward" this window (it would vanish)
        w.destroy()

    def on_shown():
        w.show()  # Teksting.vbs starts pythonw hidden; Windows applies that to our first window
        print(f"  window shown after {time.time() - t0:.1f} s")
        if splash:
            _log_handover(w, splash)
            splash.close()  # the real window is on top in the same spot: the stand-in can go

    def attach():  # runs once the window exists: let the server reach it (/api/show, watchdog)
        while "m" not in srv and not failed.is_set() and not viewer:
            time.sleep(0.05)
        if "m" in srv:
            srv["m"].WIN["w"] = w

    def on_drop(e):
        """Files dropped on the window: pywebview gives their full paths (a web page only gets the names)."""
        server = srv.get("m")
        files = (e.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if not server or not paths:
            return
        media = server.media_paths(paths)
        added = server.add_jobs({"paths": media})["added"] if media else []
        skipped = sum(1 for p in paths if not Path(p).is_dir()) - len(added)
        w.evaluate_js(f"window.tekstingDropped && tekstingDropped({len(added)}, {max(0, skipped)})")

    def on_loaded():  # every page load (loading screen, then the app): listen for drops on the new page
        try:
            from webview.dom import DOMEventHandler
            w.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True, stop_propagation=False)
        except Exception as e:
            print("  drag and drop unavailable:", e)

    w.events.closing += on_closing
    w.events.shown += on_shown
    w.events.loaded += on_loaded
    try:
        webview.start(attach, gui="edgechromium", private_mode=False, storage_path=str(DATA / "webview"),
                      icon=str(APP_DIR / "static" / "teksting.ico"))
    except Exception as e:
        print("Own window failed, using a browser:", e)
        traceback.print_exc()
        if splash:
            splash.close()
        _browser_fallback(srv, failed, viewer)
        return
    os._exit(0)  # window closed and nothing running (closing while busy only hides it)


def _log_handover(w, splash):
    """Note in the log if the real window did not land exactly where the stand-in was (a visible jump)."""
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(int(str(w.native.Handle)), ctypes.byref(r))
        real = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        print(f"  stand-in {tuple(splash.rect or ())} -> window {real}" + ("" if real == tuple(splash.rect or ()) else "  (MOVED)"))
    except Exception as e:
        print("  handover check failed:", e)


def _browser_fallback(srv, failed, viewer):
    for _ in range(600):
        if viewer or "m" in srv or failed.is_set():
            break
        time.sleep(0.05)
    if "m" in srv:
        srv["m"].open_when_ready(URL)
    else:
        import webbrowser
        webbrowser.open(URL)
    if viewer or failed.is_set():
        os._exit(0)
    while True:  # the server runs in a daemon thread; the watchdog quits when the browser is gone
        time.sleep(3600)
