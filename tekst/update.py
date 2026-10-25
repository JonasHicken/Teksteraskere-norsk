"""Updates from GitHub, so the owner can ship a new version without sending a zip.

The owner publishes with dev/publish.ps1 (pushes to the `release` branch). The app looks at that branch now and
then (only reads from GitHub: nothing about videos or the user is sent), downloads a new version into
data/update/ready/ in the background, and puts it in place the next time Teksting starts, before anything else
is imported (server.py calls at_start first, then starts itself again on the new code).

Only the app's own files are replaced (the same set dev/pack.ps1 puts in the zip): data/ and runtime/ are never
touched. Never runs in a git checkout (the owner's own copy) or in fake/test mode.

Safety:
- never while another Teksting runs (closing the window while a video transcribes keeps it running, hidden);
- never backwards: a release older than what runs (a zip made from newer code) is skipped;
- a new version that never gets as far as showing the app is rolled back at the next start, and that release
  is skipped from then on (otherwise a broken release could never be replaced by a fixed one).
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "JonasHicken/Teksteraskere-norsk"
BRANCH = "release"
TOP_FILES = {"server.py", "requirements.txt", "start.bat", "Teksting.vbs", "lag-snarveier.ps1", "LES MEG.txt"}
CRLF = (".bat", ".vbs", ".ps1", ".txt")  # Windows scripts need CRLF, as in the zip
CHECK_EVERY_S = 6 * 3600
SHA = re.compile(r"^[0-9a-f]{40}$")
STATUS = {"version": "", "ready": "", "error": "", "rolled_back": ""}  # shown in the app


def app_file(rel):
    """Is this path (inside the repo) one of the app's own files? The same rule as dev/pack.ps1."""
    parts = rel.split("/")
    if len(parts) == 1:
        return rel in TOP_FILES
    if parts[0] not in ("tekst", "static") or "" in parts or ".." in parts or "__pycache__" in parts:
        return False
    return not rel.endswith(".pyc") and (parts[0] == "static" or rel.endswith(".py"))


def _say(data, msg):
    """At startup (before tekst/launch.py opens the log) pythonw has nowhere to print: write to the log directly."""
    if sys.stdout is not None:
        print(msg)
        return
    try:
        with open(Path(data) / "teksting.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def current(app_dir):
    try:
        return (Path(app_dir) / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def enabled(app_dir):
    return not (Path(app_dir) / ".git").exists() and os.environ.get("TEKSTING_FAKE") != "1"


def wanted(data):
    """The user's choice in Settings (on unless turned off)."""
    try:
        return json.loads((Path(data) / "settings.json").read_text(encoding="utf-8")).get("auto_update", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def other_running():
    """Is another Teksting running? The same mutex tekst/splash.py holds for as long as a Teksting runs."""
    if os.name != "nt":
        return False
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, False, "Local\\Teksting.window." + os.environ.get("TEKSTING_PORT", "8765"))
    running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
    return running


def _get(url, timeout=30, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Teksting", **({"Accept": accept} if accept else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest():
    """The commit the release branch points at. Asked the way git does (no API, so no hourly limit, which a
    company network shared by many people could reach)."""
    refs = _get(f"https://github.com/{REPO}.git/info/refs?service=git-upload-pack", 15).decode("utf-8", "replace")
    m = re.search(r"([0-9a-f]{40}) refs/heads/" + re.escape(BRANCH) + r"\b", refs)
    if not m:
        raise ValueError(f"no {BRANCH} branch on GitHub")
    return m.group(1)


def behind(cur, sha):
    """Is the release older than what runs (for example a zip made from newer, unpublished code)?
    Best effort: when GitHub cannot say (unknown commit, rate limit), the release wins.
    "<sha>-local" (a zip of uncommitted code, dev/pack.ps1) counts as that commit plus newer changes."""
    cur = cur.split("-")[0]
    if not SHA.match(cur):
        return False
    try:
        r = json.loads(_get(f"https://api.github.com/repos/{REPO}/compare/{cur}...{sha}", 15,
                            "application/vnd.github+json"))
        return r.get("status") in ("behind", "identical")
    except (OSError, ValueError):
        return False


def download(sha):
    return _get(f"https://codeload.github.com/{REPO}/zip/{sha}", 120)


def _upd(data):
    return Path(data) / "update"


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def skipped(data):
    return set(_read(_upd(data) / "skip.txt").split())


def stage(data, sha, zip_bytes, based_on):
    """Unpack the app's files from GitHub's zip into data/update/ready (made complete first, then renamed).
    based_on = the version running now: if the folder is replaced by hand before the next start, this is dropped."""
    tmp, ready = _upd(data) / "incoming", _upd(data) / "ready"
    shutil.rmtree(tmp, ignore_errors=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            rel = info.filename.split("/", 1)[-1]  # GitHub puts everything in "<repo>-<sha>/"
            if info.is_dir() or not app_file(rel):
                continue
            body = z.read(info)
            if rel.endswith(CRLF):
                body = body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            out = tmp / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)
            n += 1
    if not (tmp / "server.py").exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError(f"the download for {sha[:7]} has no server.py")
    (tmp / "version.txt").write_text(sha, encoding="utf-8")
    (_upd(data) / "based_on.txt").write_text(based_on, encoding="utf-8")
    shutil.rmtree(ready, ignore_errors=True)
    tmp.rename(ready)
    return n


def staged(data):
    return current(_upd(data) / "ready")


def check(app_dir, data):
    """Download the newest release if it is new to this copy. Returns its sha, or '' if there is nothing to do."""
    sha, cur = latest(), current(app_dir)
    if sha in (cur, staged(data)) or sha in skipped(data):
        return ""
    if behind(cur, sha):
        print(f"  release {sha[:7]} is older than this copy ({cur[:7]}): skipped")
        return ""
    n = stage(data, sha, download(sha), cur)
    print(f"  update {sha[:7]} downloaded ({n} files): used from the next start")
    return sha


def _copy_in(src_root, dst_root, files, backup=None):
    for rel in files:
        dst = dst_root / rel
        if backup is not None and dst.exists():
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup / rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_root / rel, dst)


def apply_staged(app_dir, data):
    """Put a downloaded version in place. The old files go to data/update/previous; if copying fails half-way
    they are put back. Returns True if it was applied."""
    app_dir, upd = Path(app_dir), _upd(data)
    ready, prev = upd / "ready", upd / "previous"
    if not (ready / "server.py").exists():
        return False
    sha, cur = staged(data), current(app_dir)
    if sha == cur or _read(upd / "based_on.txt") != cur:  # already this version, or replaced by hand meanwhile
        shutil.rmtree(ready, ignore_errors=True)
        return False
    shutil.rmtree(prev, ignore_errors=True)
    prev.mkdir(parents=True)
    files = [p.relative_to(ready) for p in ready.rglob("*") if p.is_file()]
    added = [str(rel).replace("\\", "/") for rel in files if not (app_dir / rel).exists()]
    try:
        _copy_in(ready, app_dir, files, backup=prev)
    except OSError as e:
        _say(data, f"  update {sha[:7]} failed, keeping the old version: {e}")
        _restore(app_dir, prev, added)
        _skip(data, sha)
        shutil.rmtree(ready, ignore_errors=True)
        return False
    (upd / "pending.json").write_text(json.dumps({"sha": sha, "starts": 0, "added": added}), encoding="utf-8")
    shutil.rmtree(ready, ignore_errors=True)
    (upd / "rolled_back.txt").unlink(missing_ok=True)
    _say(data, f"  update {sha[:7]} put in place ({len(files)} files)")
    return True


def _restore(app_dir, prev, added):
    _copy_in(prev, app_dir, [p.relative_to(prev) for p in prev.rglob("*") if p.is_file()])
    for rel in added:
        (app_dir / rel).unlink(missing_ok=True)


def _skip(data, sha):
    with open(_upd(data) / "skip.txt", "a", encoding="utf-8") as f:
        f.write(sha + "\n")


def roll_back_if_failed(app_dir, data):
    """A version put in place last time that never showed the app (confirm() was not reached) is undone at the
    start after that. Returns True if it was rolled back."""
    upd = _upd(data)
    try:
        p = json.loads((upd / "pending.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    p["starts"] = p.get("starts", 0) + 1
    if p["starts"] < 2:  # the first start of the new version is this one
        (upd / "pending.json").write_text(json.dumps(p), encoding="utf-8")
        return False
    _say(data, f"  update {p.get('sha', '')[:7]} never started properly: back to the previous version")
    _restore(Path(app_dir), upd / "previous", p.get("added", []))
    _skip(data, p.get("sha", ""))
    (upd / "rolled_back.txt").write_text(p.get("sha", ""), encoding="utf-8")
    (upd / "pending.json").unlink(missing_ok=True)
    return True


def confirm(data):
    """The app has shown its page: the version running now works (no rollback)."""
    (_upd(data) / "pending.json").unlink(missing_ok=True)


def at_start(app_dir, data):
    """First thing at startup (server.py). Returns True if the files changed and Teksting must start again."""
    if not enabled(app_dir) or other_running():
        return False
    if roll_back_if_failed(app_dir, data):
        return True
    return wanted(data) and apply_staged(app_dir, data)


def restart(app_dir, old_requirements):
    """Start Teksting again on the new files and end this process. Changed Python packages: through
    Teksting.vbs, which installs them first (and shows start.bat with the error if that fails)."""
    app_dir = Path(app_dir)
    req = app_dir / "requirements.txt"
    vbs = app_dir / "Teksting.vbs"
    if os.name == "nt" and vbs.exists() and req.exists() and req.read_bytes() != old_requirements \
            and "--app" in sys.argv:
        subprocess.Popen(["wscript.exe", str(vbs)], close_fds=True)
    else:  # same console (start.bat) or none (pythonw): a detached copy has no output and the web server fails
        subprocess.Popen([sys.executable] + sys.argv, close_fds=True)
    os._exit(0)


def watch(app_dir, data, wanted_now):
    """Background thread: look for a new release shortly after start, then every few hours.
    wanted_now() says whether the user has automatic updates on (Settings)."""
    STATUS["version"] = current(app_dir)[:7]
    STATUS["ready"] = staged(data)[:7]
    rb = _upd(data) / "rolled_back.txt"
    STATUS["rolled_back"] = _read(rb)[:7]
    rb.unlink(missing_ok=True)  # told once
    if not enabled(app_dir):
        return

    def run():
        time.sleep(30)  # not while the app is starting
        while True:
            if wanted_now():
                try:
                    if check(app_dir, data):
                        STATUS["ready"] = staged(data)[:7]
                    STATUS["error"] = ""
                except Exception as e:  # offline, GitHub down, blocked by a company firewall: try again later
                    STATUS["error"] = str(e)[:200]
                    print("  update check failed:", e)
                time.sleep(CHECK_EVERY_S)
            else:
                time.sleep(60)  # turned off: notice soon when it is turned on again
    threading.Thread(target=run, daemon=True).start()
