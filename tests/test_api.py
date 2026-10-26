"""The server API end to end, with fake transcription (TEKSTING_FAKE=1, set in conftest.py)."""
import os
import re
import time
import urllib.parse
from pathlib import Path

import pytest


def transcribe(server, client, path):
    """Add a file and run the job right here (the background worker isn't started in tests)."""
    r = client.post("/api/jobs", json={"paths": [str(path)]})
    assert r.status_code == 200
    pid = r.json()["added"][0]["id"]
    server.worker.process(server.store.get(pid))
    assert server.store.get(pid)["status"] == "done"
    return pid


@pytest.fixture
def done_pid(server, client, no_sleep, make_audio):
    return transcribe(server, client, make_audio("Årsmøte på Ørland.wav", 30))


CUES = [{"start": 0.6, "end": 2.5, "text": "Hei og velkommen\ntil årsmøtet."},
        {"start": 3.0, "end": 5.0, "text": "Æøå «sitat» – … “x”", "checked": True},
        {"start": 6.0, "end": 8.0, "text": "Flyttet opp", "pos": "top"}]


# ----------------------------------------------------------------- transcription
def test_transcription_produces_cues_words_and_peaks(client, done_pid):
    d = client.get(f"/api/projects/{done_pid}").json()
    assert d["meta"]["status"] == "done" and d["meta"]["cues"] == len(d["cues"]) > 0
    assert all(c["end"] > c["start"] for c in d["cues"])
    assert d["words"] and len(d["words"][0]) == 4          # [start, end, confidence, text]
    assert d["disagree"], "the double check (fake fast model) should flag the swapped words"
    peaks = client.get(f"/api/projects/{done_pid}/peaks")
    assert peaks.status_code == 200 and len(peaks.content) > 0


def test_video_can_be_proofread_before_the_double_check_runs(server, client, no_sleep, make_audio, monkeypatch):
    seen = {}
    real = server.worker.double_check

    def spy(pid, *a):  # what the editor would get the moment the double-check starts
        seen["meta"] = dict(server.store.get(pid))
        seen["project"] = client.get(f"/api/projects/{pid}").json()
        real(pid, *a)
    monkeypatch.setattr(server.worker, "double_check", spy)
    pid = transcribe(server, client, make_audio("Kort.wav", 20))
    assert seen["meta"]["status"] == "done" and seen["meta"]["checking"] is True
    assert seen["project"]["cues"] and seen["project"]["disagree"] == []
    m = server.store.get(pid)
    assert m["checking"] is False and m["disagree"] == len(client.get(f"/api/projects/{pid}").json()["disagree"]) > 0


def test_a_failing_double_check_leaves_the_video_done(server, client, no_sleep, make_audio, monkeypatch):
    """The double-check runs after the video is ready; if the fast model fails (out of memory, broken download),
    the video must stay "done" without hints - not turn into an error."""
    real = server.engine.transcribe

    def broken(name, *a, **kw):
        if name == "small":
            raise MemoryError("not enough memory")
        return real(name, *a, **kw)
    monkeypatch.setattr(server.engine, "transcribe", broken)
    pid = client.post("/api/jobs", json={"paths": [str(make_audio("Kort.wav", 20))]}).json()["added"][0]["id"]
    try:
        server.worker.process(server.store.get(pid))
    except Exception as e:  # Worker.run would turn this into status "error"
        pytest.fail(f"process() raised {e!r}")
    m = server.store.get(pid)
    assert m["status"] == "done" and m["checking"] is False and m["cues"] > 0


def test_missing_file_is_an_error_not_a_crash(server, client, make_audio):
    p = make_audio("borte.wav", 5)
    pid = client.post("/api/jobs", json={"paths": [str(p)]}).json()["added"][0]["id"]
    p.unlink()
    server.worker.process(server.store.get(pid))
    m = server.store.get(pid)
    assert m["status"] == "error" and m["error_kind"] == "missing"


def test_unknown_project_is_404(client):
    assert client.get("/api/projects/finnesikke").status_code == 404


# ----------------------------------------------------------------- editing
def test_saving_cues_cleans_them(client, done_pid):
    client.put(f"/api/projects/{done_pid}/cues", json={"cues": CUES + [{"start": "9", "end": 10.12345, "text": 5}]})
    got = client.get(f"/api/projects/{done_pid}").json()["cues"]
    assert got[1]["checked"] is True and got[0]["checked"] is False
    assert got[2]["pos"] == "top" and "pos" not in got[0]
    assert got[3] == {"start": 9.0, "end": 10.123, "text": "5", "checked": False}


# ----------------------------------------------------------------- SRT export
def test_download_and_save_give_identical_valid_srt(client, done_pid, tmp_path):
    client.put(f"/api/projects/{done_pid}/cues", json={"cues": CUES})
    r = client.get(f"/api/projects/{done_pid}/srt")
    assert r.headers["content-type"].startswith("application/x-subrip")
    name = urllib.parse.unquote(r.headers["content-disposition"].split("UTF-8''", 1)[1])
    assert name == "Årsmøte på Ørland.srt"
    body = r.content
    assert not body.startswith(b"\xef\xbb\xbf"), "no BOM"
    assert b"\r\n" in body and b"\n" not in body.replace(b"\r\n", b""), "Windows line endings throughout"
    text = body.decode("utf-8")
    assert text.startswith("1\r\n00:00:00,600 --> 00:00:02,500\r\nHei og velkommen\r\ntil årsmøtet.\r\n")
    assert text.count(" --> ") == 3

    saved = client.post(f"/api/projects/{done_pid}/save-srt").json()
    assert Path(saved["path"]).name == "Årsmøte på Ørland.srt" and saved["backup"] is None
    assert Path(saved["path"]).read_bytes() == body


def test_saving_again_keeps_a_backup(client, done_pid):
    client.put(f"/api/projects/{done_pid}/cues", json={"cues": CUES})
    first = client.post(f"/api/projects/{done_pid}/save-srt").json()
    old = Path(first["path"]).read_bytes()
    client.put(f"/api/projects/{done_pid}/cues", json={"cues": CUES[:1]})
    second = client.post(f"/api/projects/{done_pid}/save-srt").json()
    assert Path(second["backup"]).read_bytes() == old
    assert Path(second["path"]).read_bytes().count(b" --> ") == 1
    assert not Path(second["path"]).with_suffix(".srt.tmp").exists()


def test_export_all_keeps_going_when_one_video_cannot_be_saved(server, client, no_sleep, make_audio, tmp_path):
    transcribe(server, client, make_audio("god.wav", 10, tmp_path / "a"))
    transcribe(server, client, make_audio("laast.wav", 10, tmp_path / "b"))
    (tmp_path / "b" / "laast.srt.tmp").mkdir()  # a folder where the file must go: writing there fails
    r = client.post("/api/export-all", json={"kind": "srt"}).json()
    assert r["count"] == 1 and [f["name"] for f in r["failed"]] == ["laast.wav"]
    assert (tmp_path / "a" / "god.srt").exists()
    assert not (tmp_path / "b" / "laast.srt").exists()


# ----------------------------------------------------------------- queue
def test_queue_runs_shortest_first(server, client, make_audio):
    long_, short = make_audio("lang.wav", 30), make_audio("kort.wav", 5)
    client.post("/api/jobs", json={"paths": [str(long_), str(short)]})
    jobs = client.get("/api/state").json()["jobs"]
    assert [j["name"] for j in jobs] == ["kort.wav", "lang.wav"]
    queued = [m for m in server.store.all() if m["status"] == "queued"]
    assert min(queued, key=server.queue_key)["name"] == "kort.wav"


def test_remove_deletes_the_project(client, done_pid):
    assert client.delete(f"/api/jobs/{done_pid}").status_code == 200
    assert client.get(f"/api/projects/{done_pid}").status_code == 404


def test_idle_models_are_freed_after_the_queue_is_done(server, monkeypatch):
    monkeypatch.setitem(server.engine._loaded, "large", object())
    monkeypatch.setattr(server.worker, "last_job", time.time())
    server.worker.free_idle_models()
    assert server.engine.is_loaded("large"), "kept right after a job"
    server.worker.last_job = time.time() - server.IDLE_FREE_S - 1
    server.worker.free_idle_models()
    assert not server.engine.is_loaded("large")


# ----------------------------------------------------------------- settings and page
def test_settings_round_trip(client):
    st = client.put("/api/settings", json={"burn_tools": True, "glossary": "Kygo\nTelenor\n", "bogus": 1}).json()
    assert st["settings"]["burn_tools"] is True and "bogus" not in st["settings"]
    assert st["glossary"] == "Kygo\nTelenor\n"


def test_page_links_carry_a_version_so_updates_are_never_cached(client):
    html = client.get("/").text
    links = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert links and all(re.search(r"\?v=\d+$", l) for l in links)
    assert client.get("/").headers["cache-control"] == "no-store"


def test_the_speech_map_is_saved_with_the_job_and_made_for_older_projects(server, client, done_pid):
    speech = client.get(f"/api/projects/{done_pid}/speech").json()
    assert speech and all(e > s for s, e in speech)
    server.store._dir(done_pid).joinpath("speech.json").unlink()  # a project from before this existed
    assert client.get(f"/api/projects/{done_pid}/speech").json() == speech
    assert server.store.load_json(done_pid, "speech.json") == speech


def test_dropped_files_and_folders_become_media_paths(server, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    sub = tmp_path / "mappe"
    sub.mkdir()
    (sub / "b.MOV").write_bytes(b"x")
    (sub / "c.wav").write_bytes(b"x")
    (sub / "inner").mkdir()
    got = server.media_paths([str(tmp_path / "a.mp4"), str(tmp_path / "notes.txt"), str(sub)])
    assert [os.path.basename(p) for p in got] == ["a.mp4", "b.MOV", "c.wav"]


def test_feedback_is_kept_locally_until_marked_sent(client, server):
    (server.DATA / "feedback.json").unlink(missing_ok=True)
    assert client.post("/api/feedback", json={"text": "  "}).status_code == 400
    notes = client.post("/api/feedback", json={"text": "Linjene brytes rart",
                                               "where": {"video": "a.mp4", "cue": 12, "time": 83.2, "bogus": 1}}).json()
    assert [n["text"] for n in notes] == ["Linjene brytes rart"]
    assert notes[0]["where"] == {"video": "a.mp4", "cue": 12, "time": 83.2}
    second = client.post("/api/feedback", json={"text": "Mer"}).json()[1]
    left = client.post("/api/feedback/sent", json={"ids": [notes[0]["id"]]}).json()
    assert [n["text"] for n in left] == ["Mer"]
    assert len(server.feedback_notes()) == 2, "sent notes stay in the file"
    assert client.delete(f"/api/feedback/{second['id']}").json() == []
    assert len(server.feedback_notes()) == 1
