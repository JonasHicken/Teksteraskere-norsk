"""Updates from GitHub (tekst/update.py), with GitHub faked."""
import io
import json
import zipfile

import pytest

from tekst import update

OLD, NEW = "a" * 40, "b" * 40


def github_zip(files):
    """What codeload.github.com gives: every file inside one "<repo>-<sha>/" folder."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for rel, body in files.items():
            z.writestr(f"Teksteraskere-norsk-{NEW}/{rel}", body)
    return buf.getvalue()


RELEASE = {"server.py": "new server", "tekst/engine.py": "new engine", "tekst/new_module.py": "added",
           "static/app.js": "js", "static/fonts/a.woff2": "font", "start.bat": "@echo off\nrem x\n",
           "requirements.txt": "fastapi\n", "tests/test_api.py": "not shipped", "dev/pack.ps1": "not shipped",
           "data/settings.json": "never", "README.md": "not shipped", "tekst/__pycache__/x.pyc": "never"}


@pytest.fixture
def install(tmp_path, monkeypatch):
    """An installed copy (no .git) on version OLD, with the user's data beside it."""
    app, data = tmp_path / "Teksting", tmp_path / "Teksting" / "data"
    (app / "tekst").mkdir(parents=True)
    (app / "server.py").write_text("old server")
    (app / "tekst" / "engine.py").write_text("old engine")
    (app / "requirements.txt").write_text("fastapi\n")
    (app / "version.txt").write_text(OLD)
    (data / "projects").mkdir(parents=True)
    (data / "settings.json").write_text("{}")
    monkeypatch.delenv("TEKSTING_FAKE", raising=False)
    monkeypatch.setattr(update, "other_running", lambda: False)
    monkeypatch.setattr(update, "latest", lambda: NEW)
    monkeypatch.setattr(update, "behind", lambda cur, sha: False)
    monkeypatch.setattr(update, "download", lambda sha: github_zip(RELEASE))
    return app, data


def test_a_new_release_is_downloaded_then_put_in_place_at_the_next_start(install):
    app, data = install
    assert update.check(app, data) == NEW
    assert (app / "server.py").read_text() == "old server", "nothing changes while the app runs"
    assert update.check(app, data) == "", "already waiting: not downloaded again"

    assert update.at_start(app, data) is True
    assert (app / "server.py").read_text() == "new server"
    assert (app / "tekst" / "engine.py").read_text() == "new engine"
    assert (app / "static" / "fonts" / "a.woff2").read_text() == "font", "sub-folders too"
    assert (app / "start.bat").read_bytes() == b"@echo off\r\nrem x\r\n", "Windows scripts get CRLF"
    assert update.current(app) == NEW
    for never in ("tests", "dev", "README.md", "tekst/__pycache__"):
        assert not (app / never).exists()
    assert (data / "settings.json").read_text() == "{}", "the user's data is never touched"
    assert (data / "update" / "previous" / "server.py").read_text() == "old server"

    assert update.at_start(app, data) is False, "the new version's first start: nothing more to do"
    update.confirm(data)
    assert update.at_start(app, data) is False
    assert update.check(app, data) == "", "now up to date"
    assert (app / "server.py").read_text() == "new server"


def test_a_new_version_that_never_shows_the_app_is_rolled_back_and_skipped(install):
    app, data = install
    update.check(app, data)
    assert update.at_start(app, data) is True       # put in place, restart
    assert update.at_start(app, data) is False      # the new version starts ... and crashes before confirm()
    assert update.at_start(app, data) is True       # the user tries again: rolled back
    assert (app / "server.py").read_text() == "old server"
    assert (app / "tekst" / "engine.py").read_text() == "old engine"
    assert not (app / "tekst" / "new_module.py").exists(), "files the release added are removed again"
    assert update.current(app) == OLD
    assert update.check(app, data) == "", "the broken release is not downloaded again"
    update.watch(app, data, lambda: False)
    assert update.STATUS["rolled_back"] == NEW[:7], "the app tells the user once"


def test_nothing_happens_while_another_teksting_runs(install, monkeypatch):
    app, data = install
    update.check(app, data)
    monkeypatch.setattr(update, "other_running", lambda: True)  # closed while transcribing: still running, hidden
    assert update.at_start(app, data) is False
    assert (app / "server.py").read_text() == "old server"
    monkeypatch.setattr(update, "other_running", lambda: False)
    assert update.at_start(app, data) is True


def test_an_older_release_is_not_installed_over_newer_code(install, monkeypatch):
    app, data = install
    monkeypatch.setattr(update, "behind", lambda cur, sha: True)
    assert update.check(app, data) == ""
    assert update.at_start(app, data) is False


def test_a_folder_replaced_by_hand_after_the_download_keeps_the_new_files(install):
    app, data = install
    update.check(app, data)
    (app / "version.txt").write_text("c" * 40)  # the user unpacked a newer zip before restarting
    assert update.at_start(app, data) is False
    assert (app / "server.py").read_text() == "old server"
    assert not (data / "update" / "ready").exists()


def test_turned_off_in_settings(install):
    app, data = install
    update.check(app, data)
    (data / "settings.json").write_text(json.dumps({"auto_update": False}))
    assert update.at_start(app, data) is False
    assert (app / "server.py").read_text() == "old server"


def test_never_updates_a_git_checkout(install):
    app, data = install
    update.check(app, data)
    (app / ".git").mkdir()  # the owner's own copy
    assert update.at_start(app, data) is False
    assert (app / "server.py").read_text() == "old server"


def test_a_broken_download_is_not_staged(install, monkeypatch):
    app, data = install
    monkeypatch.setattr(update, "download", lambda sha: github_zip({"README.md": "x"}))
    with pytest.raises(ValueError):
        update.check(app, data)
    assert update.at_start(app, data) is False


def test_latest_reads_the_branch_from_git_refs(monkeypatch):
    refs = (f"001e# service=git-upload-pack\n0000015b{OLD} HEAD\x00multi_ack\n"
            f"003f{'c' * 40} refs/heads/main\n0042{NEW} refs/heads/release\n0000")
    monkeypatch.setattr(update, "_get", lambda *a, **k: refs.encode())
    assert update.latest() == NEW
    monkeypatch.setattr(update, "_get", lambda *a, **k: b"<html>hotel wifi login</html>")
    with pytest.raises(ValueError):
        update.latest()


def test_the_zip_and_the_updater_ship_the_same_files():
    from pathlib import Path
    import subprocess
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True).stdout.split()
    if not tracked:
        pytest.skip("not a git checkout")
    shipped = {f for f in tracked if update.app_file(f)}
    assert {"server.py", "tekst/update.py", "static/app.js", "Teksting.vbs"} <= shipped
    assert not any(f.startswith(("tests/", "dev/", "docs/")) for f in shipped)
