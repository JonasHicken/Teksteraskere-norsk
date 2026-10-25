"""Updates from GitHub, so the owner can ship a new version without sending a zip.

The owner publishes with dev/publish.ps1 (pushes to the `release` branch). The app looks at that branch now and
then (only reads from GitHub: nothing about videos or the user is sent), downloads a new version into
data/update/ready/ in the background, and puts it in place the next time Teksting starts, before anything else
is imported (server.py calls apply_staged first, then starts itself again on the new code).

Only the app's own files are replaced (the same set dev/pack.ps1 puts in the zip): data/ and runtime/ are never
touched. Never runs in a git checkout (the owner's own copy) or in fake/test mode.
"""
import io
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "JonasHicken/Teksteraskere-norsk"
BRANCH = "release"
TOP_FILES = {"server.py", "requirements.txt", "start.bat", "Teksting.vbs", "lag-snarveier.ps1", "LES MEG.txt"}
CRLF = (".bat", ".vbs", ".ps1", ".txt")  # Windows scripts need CRLF, as in the zip
CHECK_EVERY_S = 6 * 3600
STATUS = {"version": "", "ready": "", "error": ""}  # shown on the Settings page


def app_file(rel):
    """Is this path (inside the repo) one of the app's own files? Mirrors the file list in dev/pack.ps1."""
    parts = rel.split("/")
    if len(parts) == 1:
        return rel in TOP_FILES
    if len(parts) == 2 and parts[0] == "tekst":
        return parts[1].endswith(".py")
    return len(parts) == 2 and parts[0] == "static" and parts[1] != ""


def current(app_dir):
    try:
        return (Path(app_dir) / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def enabled(app_dir):
    return not (Path(app_dir) / ".git").exists() and os.environ.get("TEKSTING_FAKE") != "1"


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Teksting", "Accept": "application/vnd.github.sha"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest():
    """The commit the release branch points at (one small request, no login needed: the repo is public)."""
    return _get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", 15).decode().strip()


def download(sha):
    return _get(f"https://codeload.github.com/{REPO}/zip/{sha}", 120)


def stage(data, sha, zip_bytes):
    """Unpack the app's files from GitHub's zip into data/update/ready (made complete first, then renamed)."""
    upd = Path(data) / "update"
    tmp, ready = upd / "incoming", upd / "ready"
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
    shutil.rmtree(ready, ignore_errors=True)
    tmp.rename(ready)
    return n


def staged(data):
    return current(Path(data) / "update" / "ready")


def check(app_dir, data):
    """Download the newest release if it is not what runs now or is already waiting. Returns its sha or ''."""
    sha = latest()
    if not sha or sha in (current(app_dir), staged(data)):
        return ""
    n = stage(data, sha, download(sha))
    print(f"  update {sha[:7]} downloaded ({n} files): used from the next start")
    return sha


def apply_staged(app_dir, data):
    """At startup: put a downloaded version in place. Returns True if the app must start again on the new code.
    The old files go to data/update/previous first; if copying fails half-way they are put back."""
    app_dir, ready = Path(app_dir), Path(data) / "update" / "ready"
    if not (ready / "server.py").exists() or not enabled(app_dir):
        return False
    prev = Path(data) / "update" / "previous"
    shutil.rmtree(prev, ignore_errors=True)
    files = [p.relative_to(ready) for p in ready.rglob("*") if p.is_file()]
    old_req = (app_dir / "requirements.txt").read_bytes() if (app_dir / "requirements.txt").exists() else b""
    done = []
    try:
        for rel in files:
            dst = app_dir / rel
            if dst.exists():
                (prev / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, prev / rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ready / rel, dst)
            done.append(rel)
    except OSError as e:
        print("  update failed, keeping the old version:", e)
        for rel in done:
            if (prev / rel).exists():
                shutil.copyfile(prev / rel, app_dir / rel)
            else:
                (app_dir / rel).unlink(missing_ok=True)
        return False
    shutil.rmtree(ready, ignore_errors=True)
    if (app_dir / "requirements.txt").read_bytes() != old_req:
        install_requirements(app_dir)
    return True


def install_requirements(app_dir):
    """Same as Teksting.vbs does after an update: keep the Python packages in step with requirements.txt."""
    uv = app_dir / "runtime" / "uv.exe"
    py = Path(sys.executable).with_name("python.exe")
    if not uv.exists():
        return
    env = {**os.environ, "UV_CACHE_DIR": str(app_dir / "runtime" / "uv-cache"),
           "UV_PYTHON_INSTALL_DIR": str(app_dir / "runtime" / "python"), "UV_PYTHON_PREFERENCE": "only-managed"}
    r = subprocess.run([str(uv), "pip", "install", "--python", str(py if py.exists() else sys.executable),
                        "--break-system-packages", "--quiet", "-r", str(app_dir / "requirements.txt")],
                       env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode == 0:
        shutil.copyfile(app_dir / "requirements.txt", app_dir / "runtime" / "requirements.installed")


def restart():
    """Start Teksting again with the same arguments (now on the new files) and end this process."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([sys.executable] + sys.argv, close_fds=True, creationflags=flags)
    os._exit(0)


def watch(app_dir, data, wanted):
    """Background thread: look for a new release shortly after start, then every few hours.
    wanted() says whether the user has automatic updates on (Settings)."""
    STATUS["version"] = current(app_dir)[:7]
    STATUS["ready"] = staged(data)[:7]
    if not enabled(app_dir):
        return

    def run():
        time.sleep(30)  # not while the app is starting
        while True:
            if wanted():
                try:
                    if check(app_dir, data):
                        STATUS["ready"] = staged(data)[:7]
                    STATUS["error"] = ""
                except Exception as e:  # offline, GitHub down, blocked by a company firewall: try again later
                    STATUS["error"] = str(e)[:200]
                    print("  update check failed:", e)
            time.sleep(CHECK_EVERY_S)
    threading.Thread(target=run, daemon=True).start()
