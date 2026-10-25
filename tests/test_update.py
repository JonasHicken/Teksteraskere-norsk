"""Updates from GitHub (tekst/update.py), with GitHub's download faked."""
import io
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
    monkeypatch.setattr(update, "latest", lambda: NEW)
    monkeypatch.setattr(update, "download", lambda sha: github_zip({
        "server.py": "new server", "tekst/engine.py": "new engine", "static/app.js": "js",
        "start.bat": "@echo off\nrem x\n", "requirements.txt": "fastapi\n",
        "tests/test_api.py": "not shipped", "dev/pack.ps1": "not shipped", "data/settings.json": "never",
        "README.md": "not shipped"}))
    installs = []
    monkeypatch.setattr(update, "install_requirements", lambda a: installs.append(a))
    return app, data, installs


def test_a_new_release_is_downloaded_then_put_in_place_at_the_next_start(install):
    app, data, installs = install
    assert update.check(app, data) == NEW
    assert (app / "server.py").read_text() == "old server", "nothing changes while the app runs"
    assert update.check(app, data) == "", "already waiting: not downloaded again"

    assert update.apply_staged(app, data) is True
    assert (app / "server.py").read_text() == "new server"
    assert (app / "tekst" / "engine.py").read_text() == "new engine"
    assert (app / "static" / "app.js").read_text() == "js"
    assert (app / "start.bat").read_bytes() == b"@echo off\r\nrem x\r\n", "Windows scripts get CRLF"
    assert update.current(app) == NEW
    assert not (app / "tests").exists() and not (app / "dev").exists() and not (app / "README.md").exists()
    assert (data / "settings.json").read_text() == "{}", "the user's data is never touched"
    assert (data / "update" / "previous" / "server.py").read_text() == "old server"
    assert installs == [], "same requirements: no package install"
    assert update.apply_staged(app, data) is False, "applied once"
    assert update.check(app, data) == "", "now up to date"


def test_changed_requirements_are_installed(install, monkeypatch):
    app, data, installs = install
    monkeypatch.setattr(update, "download", lambda sha: github_zip({"server.py": "s", "requirements.txt": "fastapi\nnew\n"}))
    update.check(app, data)
    update.apply_staged(app, data)
    assert installs == [app]


def test_never_updates_a_git_checkout(install):
    app, data, _ = install
    update.check(app, data)
    (app / ".git").mkdir()  # the owner's own copy
    assert update.apply_staged(app, data) is False
    assert (app / "server.py").read_text() == "old server"


def test_a_broken_download_is_not_staged(install, monkeypatch):
    app, data, _ = install
    monkeypatch.setattr(update, "download", lambda sha: github_zip({"README.md": "x"}))
    with pytest.raises(ValueError):
        update.check(app, data)
    assert update.apply_staged(app, data) is False
