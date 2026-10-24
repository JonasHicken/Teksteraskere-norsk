"""Teksting - local subtitle app. Run via start.bat (Windows) or: python server.py"""
import os
import sys
import time

T0 = time.time()  # for the startup timings in the log

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")              # plain downloads -> measurable progress
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

if (__name__ == "__main__" and os.name == "nt" and os.environ.get("TEKSTING_NO_BROWSER") != "1"
        and ("--app" in sys.argv or os.environ.get("TEKSTING_APP") == "1")):
    # App mode: hand over before importing anything else, so a window shows within ~0.3 s (tekst/launch.py);
    # everything below then loads beside it
    from tekst import splash
    early = splash.early()  # stand-in window first (ctypes only), then the rest
    from tekst import launch
    launch.main(T0, early)
    raise SystemExit

import json
import mimetypes
import re
import socket
import subprocess
import threading
import traceback
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from tekst import burn, compare, segment
from tekst.engine import MODELS, PEAK_RATE, Cancelled, Engine, compute_peaks, media_duration, peaks_from_audio
from tekst.spell import Speller
from tekst.learn import Learner
from tekst.store import Store

APP_DIR = Path(__file__).resolve().parent
DATA = Path(os.environ.get("TEKSTING_DATA", APP_DIR / "data"))
os.environ.setdefault("HF_HOME", str(DATA / "hf-cache"))
PORT = int(os.environ.get("TEKSTING_PORT", "8765"))

store = Store(DATA)
engine = Engine(DATA / "models")
speller = Speller(DATA / "dictionaries")
learner = Learner(DATA / "corrections.json")
app = FastAPI()


# ------------------------------------------------------------------ worker ---
def keep_awake(on):
    """Stop Windows from sleeping while a job runs (only affects this thread)."""
    if os.name == "nt":
        import ctypes
        flags = 0x80000000 | (0x00000001 if on else 0)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)


def hint_text(settings):
    """Glossary terms + learned corrections, given to the model as hotwords."""
    if not settings.get("hotwords", True):
        return None
    seen, terms = set(), []
    for t in store.glossary_terms() + learner.hint_words():
        if t.lower() not in seen:
            seen.add(t.lower())
            terms.append(t)
    return ", ".join(terms)[:600] or None


def allow_set():
    return store.glossary_allow() | frozenset(w.lower() for t in learner.hint_words() for w in t.split())


def seg_params(settings, pid):
    """Segmentation rules for this project (its language decides how abbreviations are written out)."""
    return segment.params(settings["rules"], collapse_repeats=settings.get("collapse_repeats", False),
                          lang=store.get(pid).get("language") or "no")


def finish_cues(pid, words, settings):
    """Segment, apply learned corrections, store as the new baseline. Returns cues."""
    p = seg_params(settings, pid)
    cues = segment.make_cues(words, p)
    fixes = learner.apply(cues, wrap=lambda t: segment.wrap_text(t, p), max_chars=p.max_chars + p.char_slack)
    store.save_cues(pid, cues, edited=False)
    store.save_json(pid, "cues_orig.json", cues)
    store.save_json(pid, "autofix.json", fixes)
    return cues, fixes


def safe_update(pid, **kw):
    """store.update that ignores a project deleted meanwhile (must never kill a worker thread)."""
    try:
        store.update(pid, **kw)
    except KeyError:
        pass


class Tracker:
    """Turns phase reports from the engine into overall progress, speed and time left.

    Each job has a plan: [(status, phase, expected seconds)]. Progress is time-weighted, so 50 %
    means about half the time. While text is being produced we measure the real speed and use it
    for the rest of the job. The UI gets {progress, rate, cap, pt} and moves the bar smoothly
    between reports instead of jumping every 30-60 s.
    """

    def __init__(self, pid, plan, scale=1.0):
        self.pid, self.scale = pid, scale
        total = sum(p[2] for p in plan) or 1.0
        self.ranges, self.order, acc = {}, [], 0.0
        for st, ph, sec in plan:
            self.ranges[(st, ph)] = (acc / total, (acc + sec) / total, sec)
            self.order.append((st, ph))
            acc += sec
        self.cur, self.first, self.last_write = None, None, 0.0

    def reporter(self, status):
        return lambda p, phase, cap=None: self.report(status, phase, p, cap)

    def report(self, status, phase, p, cap=None):
        key = (status, phase)
        if key not in self.ranges:
            return
        lo, hi, sec = self.ranges[key]
        now = time.time()
        changed = key != self.cur
        if changed:
            self.cur, self.first = key, (now, p)
        elif now - self.last_write < 0.5 and p < 1.0:
            return
        self.last_write = now
        total = lo + (hi - lo) * p
        cap_total = lo + (hi - lo) * (1.0 if cap is None else max(p, cap))
        rate = (hi - lo) / max(1.0, sec * self.scale)              # expected progress per second
        t1, p1 = self.first
        if phase in ("decode", "rescue") and p > p1 and now - t1 > 8:
            measured = (hi - lo) * (p - p1) / (now - t1)
            rate = measured  # re-listening varies most (a fast debate: ~30x its estimate), so it is measured too
            if phase == "decode":
                self.scale = min(4.0, max(0.25, ((hi - lo) / sec) / measured))  # applies to later phases too
        # time left: rest of this phase at the current rate + later phases at the (corrected) estimate
        later = self.order[self.order.index(key) + 1:]
        eta = (hi - total) / rate + sum(self.ranges[k][2] for k in later) * self.scale
        store.update(self.pid, status=status, phase=phase, progress=round(total, 5), cap=round(cap_total, 5),
                     rate=rate, pt=now, eta=eta)


def time_scale():
    """How much slower/faster this PC is than our built-in estimates (from finished jobs)."""
    r = sorted(m["took"] / m["expected"] for m in store.all()
               if m.get("status") == "done" and m.get("took") and m.get("expected"))[-9:]
    return min(4.0, max(0.25, r[len(r) // 2])) if r else 1.0


IDLE_FREE_S = float(os.environ.get("TEKSTING_IDLE_FREE", "60"))  # free the models 1 min after the queue ran dry


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.wake = threading.Event()
        self.stop_job = threading.Event()
        self.paused = False
        self.current = None
        self.downloading = {}  # model -> progress (0-1)

    def run(self):
        while True:
            queued = [] if self.paused else [m for m in store.all() if m["status"] == "queued"]
            job = min(queued, key=queue_key) if queued else None
            if job is None:
                keep_awake(False)
                self.free_idle_models()
                self.wake.wait(2)
                self.wake.clear()
                continue
            keep_awake(True)
            self.current = job["id"]
            self.stop_job.clear()
            try:
                self.process(job)
            except Cancelled:
                safe_update(job["id"], status="cancelled", eta=None, message="")
            except KeyError:
                pass  # project deleted while it was being transcribed
            except Exception as e:
                traceback.print_exc()
                safe_update(job["id"], status="error", eta=None, message=str(e)[:300])
            finally:
                self.current = None
                self.downloading.clear()
                engine.drop_audio()
                self.last_job = time.time()

    last_job = 0.0

    def free_idle_models(self):
        """Empty queue: give the RAM back (large ~1.5 GB, small ~0.26 GB) IDLE_FREE_S after the last job.
        Only transcription uses the models (the editor has no model features: a human ear beats the model there),
        so proofreading runs without them. A video added later reloads them in ~1-5 s."""
        if engine._loaded and time.time() - self.last_job >= IDLE_FREE_S:
            gone = engine.unload()
            if gone:
                print("freed idle models:", ", ".join(gone))

    def ensure_model(self, pid, name):
        """Download the model if needed. Returns False (and marks the job) if it failed."""
        if engine.is_ready(name):
            return True
        store.update(pid, status="downloading", progress=0.0, message="", error_kind=None, dl_model=name)

        def dl(p):
            self.downloading[name] = p
            store.update(pid, progress=p)

        try:
            engine.download(name, dl, self.stop_job)
        except Cancelled:
            raise
        except Exception as e:
            traceback.print_exc()
            store.update(pid, status="error", error_kind="download", eta=None, message=str(e)[:200])
            return False
        finally:
            self.downloading.pop(name, None)
        return True

    def process(self, job):
        pid, name = job["id"], job["model"]
        if not Path(job["path"]).exists():
            store.update(pid, status="error", error_kind="missing", message=job["path"])
            return
        settings = store.settings()
        double = bool(settings.get("double_check")) and name != "small"
        if not self.ensure_model(pid, name):
            return
        if double and not self.ensure_model(pid, "small"):
            return
        prompt = hint_text(settings)
        t0 = time.time()
        dur = job.get("duration") or media_duration(job["path"]) or 600.0
        plan = [("transcribing", ph, sec) for ph, sec in engine.plan(name, dur, rescue=True)]
        plan.append(("finishing", "finish", dur / 120 + 2))
        tr = Tracker(pid, plan, time_scale())
        store.update(pid, status="transcribing", phase=None, progress=0.0, eta=None, rate=0, pt=None, double=double,
                     expected=sum(p[2] for p in plan))
        words = engine.transcribe(name, job["path"], job["language"], prompt,
                                  tr.reporter("transcribing"), self.stop_job, rescue=True)
        store.save_words(pid, words)
        rescued = []
        for w in words:
            if w.get("r"):
                if rescued and w["s"] - rescued[-1]["e"] < 1.0:
                    rescued[-1]["e"] = w["e"]
                else:
                    rescued.append({"s": w["s"], "e": w["e"]})
        store.save_json(pid, "rescued.json", rescued)
        cues, fixes = finish_cues(pid, words, settings)
        store.save_json(pid, "disagree.json", [])
        tr.report("finishing", "finish", 0.0)
        try:
            peaks_for(pid)
        except Exception:
            traceback.print_exc()
        # Ready to proofread now: the double-check below only adds "Alternativ" hints, and the editor picks
        # them up when they arrive. Before, the video waited for it (~40 % of the job) before it could be opened.
        store.update(pid, status="done", progress=1.0, eta=None, message="", finished=time.time(),
                     took=time.time() - t0, disagree=0, rescued=len(rescued), checking=double, check=0.0,
                     autofixed=len(fixes), edit_rate=0.0, work_seconds=0)
        if double:
            self.double_check(pid, job, words, rescued, prompt, dur)

    def double_check(self, pid, job, words, rescued, prompt, dur):
        """The fast model transcribes again; where it hears something else, the editor shows a hint.
        Runs after the video is marked done (status stays "done"; meta `checking` / `check` show it)."""
        try:
            alt = engine.transcribe("small", job["path"], job["language"], prompt, check_reporter(pid, dur), self.stop_job)
        except Cancelled:  # deleted or retried meanwhile: the video itself is fine, just without hints
            safe_update(pid, checking=False)
            return
        except Exception:  # the fast model failed (memory, broken download ...): same, never mark the video failed
            traceback.print_exc()
            safe_update(pid, checking=False)
            return
        allow = allow_set()
        is_word = lambda w: not speller.unknown(w, job["language"], allow)  # noqa: E731
        disagree = compare.disagreements(words, alt, is_word, lang=job["language"] or "no")
        # recovered stretches are flagged already; don't flag them twice
        disagree = [d for d in disagree if not any(r["s"] - 0.3 <= d["s"] and d["e"] <= r["e"] + 0.3 for r in rescued)]
        try:
            if store.get(pid).get("status") != "done":
                safe_update(pid, checking=False)
                return  # sent back to the queue meanwhile: these hints belong to the old transcript
        except KeyError:
            return
        store.save_json(pid, "disagree.json", disagree)
        safe_update(pid, checking=False, check=1.0, disagree=len(disagree))


def check_reporter(pid, dur):
    """Progress of the double-check as meta `check` (0-1), at most once a second."""
    plan = engine.plan("small", dur)
    total = sum(sec for _, sec in plan) or 1.0
    ranges, acc = {}, 0.0
    for ph, sec in plan:
        ranges[ph] = (acc / total, sec / total)
        acc += sec
    last = [0.0]

    def report(p, phase, cap=None):
        if phase not in ranges or (time.time() - last[0] < 1.0 and p < 1.0):
            return
        last[0] = time.time()
        lo, w = ranges[phase]
        safe_update(pid, check=round(lo + w * p, 3))
    return report


class Exporter(threading.Thread):
    """Burns subtitles into videos, one at a time, separate from transcription."""

    def __init__(self):
        super().__init__(daemon=True)
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.current = None

    def run(self):
        while True:
            job = next((m for m in store.all() if (m.get("export") or {}).get("status") == "queued"), None)
            if job is None:
                self.wake.wait(2)
                self.wake.clear()
                continue
            pid = job["id"]
            self.current = pid
            self.stop.clear()
            last = [0.0]

            def prog(p):
                if time.time() - last[0] > 0.7 or p >= 1:
                    last[0] = time.time()
                    safe_update(pid, export={"status": "running", "progress": p})

            try:
                store.update(pid, export={"status": "running", "progress": 0.0})
                out = burn.burn(job["path"], store.cues(pid), store.settings()["style"],
                                store._dir(pid) / "burn", prog, self.stop)
                safe_update(pid, export={"status": "done", "progress": 1.0, "path": str(out), "at": time.time()})
            except burn.Cancelled:
                safe_update(pid, export={"status": "cancelled"})
            except KeyError:
                pass  # project deleted before the burn-in started
            except Exception as e:
                traceback.print_exc()
                safe_update(pid, export={"status": "error", "message": str(e)[:300]})
            finally:
                self.current = None


def peaks_for(pid):
    f = store._dir(pid) / "peaks.bin"
    if not f.exists():
        path = store.get(pid)["path"]
        audio = engine.cached_audio(path)
        f.write_bytes(peaks_from_audio(audio) if audio is not None else compute_peaks(path))
    return f


worker = Worker()
exporter = Exporter()


# --------------------------------------------------------------- helpers ---
RUNNING = ("downloading", "loading", "transcribing", "checking", "finishing")


def queue_key(m):
    """Shortest video first (transcription time follows the length, not the file size), so the first
    videos are ready to proofread while the long ones are still running. Unknown length: last, by size."""
    if m.get("duration"):
        return (0, m["duration"], m["created"])
    try:
        size = Path(m["path"]).stat().st_size
    except OSError:
        size = float("inf")
    return (1, size, m["created"])


def list_order(jobs):
    """The list on the Videoer page: the one being transcribed, then the queue in the order it will run,
    then everything else (finished, errors) in the order it was added."""
    running = [m for m in jobs if m["status"] in RUNNING]
    queued = sorted((m for m in jobs if m["status"] == "queued"), key=queue_key)
    rest = [m for m in jobs if m["status"] not in RUNNING and m["status"] != "queued"]
    return running + queued + rest


def state():
    jobs = list_order(store.all())
    return {"settings": store.settings(), "models": engine.status(), "jobs": jobs,
            "paused": worker.paused, "current": worker.current, "data_dir": str(DATA),
            "glossary": store.glossary(), "now": time.time(), "time_scale": time_scale()}


def project(pid):
    try:
        return store.get(pid)
    except KeyError:
        raise HTTPException(404, "Project not found")


PICKER = r"""
import json, sys, tkinter as tk
from tkinter import filedialog
# Tell Windows we draw at the real screen resolution; otherwise it upscales the dialog (blurry).
try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor (Win 8.1+)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()        # older Windows
except Exception:
    pass
r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True); r.update()
p = filedialog.askopenfilenames(parent=r, title=sys.argv[1], filetypes=[
    ("Video / audio", "*.mp4 *.mov *.m4v *.mkv *.avi *.webm *.wmv *.mp3 *.wav *.m4a *.aac *.flac *.ogg"),
    ("*", "*.*")])
print(json.dumps(list(p)))
"""


# ------------------------------------------------------------------- API ---
@app.get("/api/ping")
def ping():
    return {"app": "teksting"}


LAST_SEEN = [time.time()]


@app.get("/api/state")
def get_state():
    LAST_SEEN[0] = time.time()
    APP_LOADED.set()
    return {**state(), "app_mode": APP_MODE}


@app.post("/api/pick")
def pick(title: str = Body("Velg videoer", embed=True)):
    try:
        out = subprocess.run([sys.executable, "-c", PICKER, title], capture_output=True, text=True, timeout=600)
        paths = json.loads(out.stdout.strip() or "[]")
    except Exception as e:
        raise HTTPException(500, f"Could not open the file picker: {e}")
    return add_jobs({"paths": paths})


@app.post("/api/jobs")
def add_jobs(body: dict = Body(...)):
    s = store.settings()
    added = []
    for p in body.get("paths", []):
        if Path(p).is_file():
            added.append(store.create(str(Path(p).resolve()), body.get("model") or s["model"],
                                      body.get("language") or s["language"], media_duration(p)))
    worker.wake.set()
    return {"added": added, **state()}


@app.post("/api/jobs/{pid}/retry")
def retry(pid: str):
    m = project(pid)
    store.update(pid, status="queued", progress=0.0, message="", eta=None, error_kind=None,
                 model=store.settings()["model"] if m["status"] != "done" else m["model"])
    worker.wake.set()
    return state()


@app.post("/api/jobs/{pid}/cancel")
def cancel(pid: str):
    m = project(pid)
    if worker.current == pid:
        worker.stop_job.set()
    elif m["status"] == "queued":
        store.update(pid, status="cancelled")
    return state()


@app.delete("/api/jobs/{pid}")
def remove(pid: str):
    m = project(pid)
    if (m.get("export") or {}).get("status") == "queued":
        store.update(pid, export={"status": "cancelled"})  # so the exporter doesn't pick it up meanwhile
    for busy_with, stop in ((lambda: worker.current, worker.stop_job), (lambda: exporter.current, exporter.stop)):
        if busy_with() == pid:
            stop.set()
            for _ in range(100):  # burn-in stops within a second; transcription at its next step
                if busy_with() != pid:
                    break
                time.sleep(0.1)
    learner.forget_project(pid)
    store.delete(pid)
    return state()


@app.post("/api/queue")
def queue(paused: bool = Body(..., embed=True)):
    worker.paused = paused
    worker.wake.set()
    return state()


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    if "glossary" in body:
        store.save_glossary(body.pop("glossary"))
    store.save_settings(body)
    return state()


@app.post("/api/glossary")
def add_glossary(word: str = Body(..., embed=True)):
    store.add_to_glossary(word.strip())
    return {"glossary": store.glossary()}


@app.post("/api/models/{name}/download")
def download_model(name: str):
    if name not in MODELS:
        raise HTTPException(404)
    if worker.current or name in worker.downloading:
        raise HTTPException(409, "busy")

    def go():
        worker.downloading[name] = 0.0
        try:
            engine.download(name, lambda p: worker.downloading.__setitem__(name, p), threading.Event())
        except Exception:
            traceback.print_exc()
        finally:
            worker.downloading.pop(name, None)

    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


@app.get("/api/downloads")
def downloads():
    return worker.downloading


@app.delete("/api/models/{name}")
def delete_model(name: str):
    if name not in MODELS:
        raise HTTPException(404)
    if worker.current or name in worker.downloading:
        raise HTTPException(409, "busy")  # a job (or its double-check) may be using it right now
    engine.delete(name)
    return state()


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    m = project(pid)
    s = store.settings()
    return {"meta": m, "cues": store.cues(pid), "rules": s["rules"], "style": s["style"],
            "pause_on_type": s.get("pause_on_type", True), "disagree": store.load_json(pid, "disagree.json", []),
            "rescued": store.load_json(pid, "rescued.json", []),
            "autofix": store.load_json(pid, "autofix.json", []),
            "peak_rate": PEAK_RATE,
            # model words as [start, end, confidence, text]: uncertain-word hints and snapping in the editor
            "words": [[w["s"], w["e"], w.get("p", 1.0), w["w"].strip()] for w in store.words(pid)]}


@app.put("/api/projects/{pid}/cues")
def put_cues(pid: str, cues: list = Body(..., embed=True)):
    project(pid)
    clean = [{"start": round(float(c["start"]), 3), "end": round(float(c["end"]), 3), "text": str(c["text"]),
              "checked": bool(c.get("checked")), **({"pos": "top"} if c.get("pos") == "top" else {})} for c in cues]
    store.save_cues(pid, clean)
    schedule_stats(pid)
    return {"ok": True, "saved": time.time()}


_stat_timers = {}


def schedule_stats(pid, delay=4.0):
    """Recompute edit rate + learned corrections a few seconds after the last save."""
    old = _stat_timers.pop(pid, None)
    if old:
        old.cancel()
    t = threading.Timer(delay, compute_stats, args=(pid,))
    t.daemon = True
    _stat_timers[pid] = t
    t.start()


def compute_stats(pid):
    try:
        m = store.get(pid)
        orig = store.load_json(pid, "cues_orig.json", None)
        if orig is None:
            s = store.settings()
            orig = segment.make_cues(store.words(pid), seg_params(s, pid))
            store.save_json(pid, "cues_orig.json", orig)
        rate = learner.update_project(pid, orig, store.cues(pid))
        if m.get("edit_rate") != rate:
            store.update(pid, edit_rate=rate)
    except KeyError:
        pass
    except Exception:
        traceback.print_exc()


@app.post("/api/projects/{pid}/resume")
def resume(pid: str, sel: int = Body(...), t: float = Body(...)):
    """Where proofreading stopped (selected subtitle + video time); the editor opens there next time."""
    project(pid)
    safe_update(pid, resume={"sel": max(0, int(sel)), "t": max(0.0, float(t))})
    return {"ok": True}


@app.post("/api/projects/{pid}/worktime")
def worktime(pid: str, seconds: float = Body(..., embed=True)):
    project(pid)
    with store.lock:
        m = store.get(pid)
        store.update(pid, work_seconds=round(float(m.get("work_seconds") or 0) + max(0.0, min(float(seconds), 120.0)), 1))
    return {"ok": True}


@app.get("/api/learned")
def learned():
    return {"rules": learner.rules(), "min_videos": 2}


@app.put("/api/learned")
def set_learned(key: str = Body(...), state: str = Body(...)):
    if state not in ("auto", "on", "off", "delete"):
        raise HTTPException(400)
    learner.set_state(key, state)
    return {"rules": learner.rules()}


@app.post("/api/projects/{pid}/resegment")
def resegment(pid: str):
    project(pid)
    cues, fixes = finish_cues(pid, store.words(pid), store.settings())
    store.update(pid, edited=False, autofixed=len(fixes))
    schedule_stats(pid)
    return {"cues": cues, "autofix": fixes}


@app.post("/api/spell")
def spell(texts: list = Body(...), language: str = Body("no")):
    allow = allow_set()
    return {"unknown": [speller.unknown(t, language, allow) for t in texts]}


@app.post("/api/wrap")
def wrap(text: str = Body(..., embed=True)):
    return {"text": segment.wrap_text(text, segment.params(store.settings()["rules"]))}


def srt_bytes(pid):
    """The SRT file exactly as both exports write it: UTF-8 without BOM, Windows line endings (CRLF).
    (Before, the download had LF and the saved file CRLF, because write_text translated on Windows.)"""
    return segment.to_srt(store.cues(pid)).replace("\n", "\r\n").encode("utf-8")


@app.get("/api/projects/{pid}/srt")
def srt(pid: str):
    m = project(pid)
    name = Path(m["name"]).stem + ".srt"
    return Response(srt_bytes(pid), media_type="application/x-subrip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}"})


@app.get("/api/projects/{pid}/peaks")
def peaks(pid: str):
    project(pid)
    try:
        return Response(peaks_for(pid).read_bytes(), media_type="application/octet-stream")
    except Exception:
        return Response(b"", media_type="application/octet-stream")


@app.post("/api/projects/{pid}/burn")
def burn_video(pid: str):
    m = project(pid)
    if m["status"] != "done":
        raise HTTPException(409, "not transcribed yet")
    if not Path(m["path"]).exists():
        raise HTTPException(404, "Video file has moved or been deleted")
    store.update(pid, export={"status": "queued", "progress": 0.0})
    exporter.wake.set()
    return state()


@app.post("/api/projects/{pid}/burn/cancel")
def burn_cancel(pid: str):
    m = project(pid)
    if exporter.current == pid:
        exporter.stop.set()
    elif (m.get("export") or {}).get("status") == "queued":
        store.update(pid, export={"status": "cancelled"})
    return state()


@app.post("/api/export-all")
def export_all(kind: str = Body(..., embed=True)):
    done = [m for m in store.all() if m["status"] == "done" and Path(m["path"]).exists()]
    saved, failed = [], []
    for m in done:
        if kind == "srt":
            try:  # one locked file or folder must not stop the rest
                saved.append(write_srt_next_to_video(m["id"], m)["path"])
            except OSError as e:
                failed.append({"name": m["name"], "message": e.strerror or str(e)})
        elif kind == "burn" and (m.get("export") or {}).get("status") not in ("queued", "running"):
            store.update(m["id"], export={"status": "queued", "progress": 0.0})
            saved.append(m["path"])
    exporter.wake.set()
    return {"count": len(saved), "paths": saved, "failed": failed, **state()}


@app.post("/api/projects/{pid}/save-srt")
def save_srt(pid: str):
    m = project(pid)
    try:
        return write_srt_next_to_video(pid, m)
    except OSError as e:
        raise HTTPException(500, f"{m['name']}: {e.strerror or e}")


def write_srt_next_to_video(pid, m):
    """Write the new file first; only then keep the old one as .srt.bak and put the new one in place,
    so a failed write can never leave the video without its .srt."""
    target = Path(m["path"]).with_suffix(".srt")
    tmp = target.with_suffix(".srt.tmp")
    tmp.write_bytes(srt_bytes(pid))
    backup = None
    try:
        if target.exists():
            backup = target.with_suffix(".srt.bak")
            target.replace(backup)
        tmp.replace(target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return {"path": str(target), "backup": str(backup) if backup else None}


@app.post("/api/open-folder")
def open_folder(path: str = Body(..., embed=True)):
    p = Path(path)
    folder = p if p.is_dir() else p.parent
    if os.name == "nt":
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(folder))  # noqa
    return {"ok": True}


@app.get("/api/projects/{pid}/media")
def media(pid: str, request: Request):
    m = project(pid)
    path = Path(m["path"])
    if not path.exists():
        raise HTTPException(404, "Video file has moved or been deleted")
    size = path.stat().st_size
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    rng = request.headers.get("range")
    start, end = 0, size - 1
    if rng and rng.startswith("bytes="):
        a, _, b = rng[6:].split(",")[0].partition("-")
        if a:
            start = int(a)
            end = int(b) if b else size - 1
        elif b:
            start = max(0, size - int(b))
        end = min(end, size - 1)
        if start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    def body():
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(body(), status_code=206 if rng else 200, media_type=ctype, headers=headers)


@app.post("/api/quit")
def quit_app():
    def bye():
        burn.abort_all()  # a running burn-in starts again next time (its status stays "running")
        os._exit(0)
    threading.Timer(0.4, bye).start()
    return {"ok": True}


WIN = {"w": None, "hidden": False}  # Teksting's own window (app mode), set by tekst/launch.py


@app.post("/api/show")
def show_window():
    """A second start (shortcut clicked again) brings the existing window forward instead of opening another."""
    w = WIN["w"]
    if not w:
        return {"ok": False}
    WIN["hidden"] = False
    w.show()
    try:
        if str(w.native.WindowState) == "Minimized":
            w.restore()
    except Exception:
        pass
    return {"ok": True}


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """The app window keeps an HTTP cache between runs. Without this it reused old app.js/editor.js after an
    update (no request at all). "no-cache" = always ask; unchanged files cost only a 304."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _asset_version():
    return str(int(max(p.stat().st_mtime for p in (APP_DIR / "static").iterdir() if p.is_file())))


@app.get("/")
def index():
    # ?v=<newest file time> on every /static/ link: an updated app can never run with yesterday's cached files
    html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    v = _asset_version()
    html = re.sub(r'((?:src|href)="/static/[^"?]+)"', lambda m: f'{m.group(1)}?v={v}"', html)
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


# ------------------------------------------------------------------ main ---
def port_in_use():
    """Fast check: on Windows, connecting to a port nobody listens on takes ~2 s before it fails,
    while a local server answers at once - so give up after 0.3 s."""
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def already_running():
    if not port_in_use():
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/ping", timeout=1) as r:
            return json.load(r).get("app") == "teksting"
    except Exception:
        return False


APP_MODE = "--app" in sys.argv or os.environ.get("TEKSTING_APP") == "1"


def find_app_browser():
    """Edge (on every Windows 10/11) or Chrome, for a window without address bar and tabs."""
    cands = []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                      Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"]
    return next((str(p) for p in cands if p.exists()), None)


def open_ui(url):
    exe = find_app_browser() if os.name == "nt" else None
    if exe:
        try:
            subprocess.Popen([exe, f"--app={url}", "--window-size=1440,900"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def wait_until_ready():
    """Wait for the server to answer, so the window never shows a 'site not available' page."""
    for _ in range(600):  # up to 30 s on a slow PC
        if UVICORN:  # app mode: our own server says when it listens (no 0.3 s port checks while it starts)
            if UVICORN[0].started:
                return
        elif already_running():
            return
        time.sleep(0.05)


APP_LOADED = threading.Event()  # set by the first /api/state: the app page is up


def warm_speller():
    """Loading the dictionary takes ~10 s of pure Python. It waits until the app page has loaded: while it
    runs, the web server answers slowly (it shares Python with it), and starting it with the server made the
    loading screen's ping and the app's files take ~4 s longer (measured 2026-10-15: app loaded 9.4 s -> 5.1 s
    after launch). Spelling flags are ready ~10 s after the app shows. Tried and rejected (2026-10-09): a
    pickled copy loads in 3.7 s but freezes the whole app for ~3 s in one go; a chunked copy took 8.9 s with
    2 s pauses."""
    wait_until_ready()
    APP_LOADED.wait(30)  # no window at all (or it failed): warm anyway
    time.sleep(0.5)      # let the first screen draw
    speller.warm(store.settings()["language"])


def open_when_ready(url):
    wait_until_ready()
    open_ui(url)


def busy():
    return bool(worker.current or exporter.current or any(
        (m["status"] == "queued" and not worker.paused) or (m.get("export") or {}).get("status") in ("queued", "running")
        for m in store.all()))


def watchdog():
    """In app mode there is no console: quit when the window has been closed and nothing is running."""
    limit = float(os.environ.get("TEKSTING_IDLE_EXIT", "90"))
    while True:
        time.sleep(min(20.0, limit / 2))
        if WIN["w"]:  # own window: quit once it is hidden and the last job is done
            if WIN["hidden"] and not busy():
                os._exit(0)
        elif time.time() - LAST_SEEN[0] > limit and not busy():
            os._exit(0)


def start_services():
    """Everything but the web server: clean up leftovers, restart interrupted jobs, start the workers."""
    store.cleanup()
    for m in store.all():  # jobs that were running when the app closed start again
        if m["status"] in RUNNING:
            store.update(m["id"], status="queued", progress=0.0, eta=None)
        if m.get("checking"):  # the double-check was cut off: the video is fine, it just has no hints
            store.update(m["id"], checking=False)
        if (m.get("export") or {}).get("status") == "running":
            store.update(m["id"], export={"status": "queued"})
    worker.start()
    exporter.start()
    threading.Thread(target=warm_speller, daemon=True).start()


def port_free():
    """Instant when the port is free (the usual case at startup): binding a test socket works. Only when that
    fails do we ask with port_in_use(), which costs ~0.3 s when nobody answers (a port in TIME_WAIT)."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", PORT))
            return True
        except OSError:
            pass
    return not port_in_use()


UVICORN = []  # the app-mode web server, so wait_until_ready() can ask it directly instead of polling the port


def serve_in_background():
    """App mode (tekst/launch.py): the window owns the main thread, so the server runs beside it."""
    if not port_free():
        raise RuntimeError(f"Port {PORT} is used by another program. Set TEKSTING_PORT to another number.")
    start_services()
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    UVICORN.append(server)
    threading.Thread(target=server.run, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    print("\n  Teksting is running:", f"http://127.0.0.1:{PORT}/")


def main():
    """Without the own window: dev (python server.py), or app mode outside Windows."""
    url = f"http://127.0.0.1:{PORT}/"
    if already_running():
        open_ui(url)
        return
    if port_in_use():
        print(f"Port {PORT} is used by another program. Set TEKSTING_PORT to another number.")
        return
    start_services()
    if os.environ.get("TEKSTING_NO_BROWSER") != "1":
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    if APP_MODE:
        threading.Thread(target=watchdog, daemon=True).start()
    print("\n  Teksting is running:", url)
    print("  Keep this window open while you work. Close it to quit.\n")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
