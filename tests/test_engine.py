"""Engine helpers that don't need a speech model."""
import numpy as np

from tekst.engine import PEAK_RATE, Engine, peaks_from_audio, physical_cores


def test_physical_cores_is_clamped():
    assert 4 <= physical_cores() <= 8


def test_peaks_one_value_per_50th_second_and_scaled_to_a_byte():
    sr = 16000
    audio = np.zeros(sr * 2, dtype=np.float32)
    audio[sr:] = 0.5  # silence, then sound
    p = peaks_from_audio(audio, sr)
    assert len(p) == 2 * PEAK_RATE
    assert max(p[:PEAK_RATE]) == 0 and min(p[PEAK_RATE:]) > 200
    assert peaks_from_audio(np.zeros(10, dtype=np.float32), sr) == b""


def test_unload_keeps_what_is_asked_for(tmp_path):
    e = Engine(tmp_path)
    e._loaded.update(large=object(), small=object())
    assert sorted(e.unload(keep={"large"})) == ["small"]
    assert e.is_loaded("large") and not e.is_loaded("small")
    assert e.unload() == ["large"] and e.unload() == []



def test_speech_holes_are_speech_stretches_without_words():
    from tekst.engine import speech_holes
    w = lambda s, e: {"w": "x", "s": s, "e": e}  # noqa: E731
    words = [w(1.0, 1.4), w(1.5, 2.0), w(4.0, 4.5)]
    # speech 0.5-5.0: holes before the first word (0.5 s: too short), 2.0-4.0, after the last (0.5 s: too short)
    assert speech_holes([(0.5, 5.0)], words, 0.6) == [(2.0, 4.0)]
    assert speech_holes([(10.0, 11.0)], words, 0.6) == [(10.0, 11.0)]  # speech with no words at all
    assert speech_holes([(0.9, 1.6)], words, 0.6) == []                # fully covered


def test_a_re_heard_word_on_top_of_an_existing_one_is_not_added_twice():
    from tekst.engine import _overlaps
    have = [{"s": 1.0, "e": 1.4}, {"s": 2.0, "e": 2.5}]
    assert _overlaps(have, {"s": 2.05, "e": 2.45})
    assert not _overlaps(have, {"s": 2.6, "e": 3.0})


def test_re_listening_drops_a_repeat_of_the_neighbouring_word(monkeypatch):
    """Seen on a debate clip: the re-heard stretch ended on "Og" and the main pass went on with "Og": "Og Og"."""
    import threading
    import numpy as np
    from tekst import engine as E
    eng = E.Engine.__new__(E.Engine)
    main = [{"w": " strømpriser.", "s": 1.0, "e": 1.6, "p": 0.9}, {"w": " Og", "s": 4.0, "e": 4.3, "p": 0.9},
            {"w": " togene", "s": 4.3, "e": 4.7, "p": 0.9}]
    heard = [{"w": " Vi", "s": 2.0, "e": 2.3, "p": 0.9}, {"w": " venter.", "s": 2.3, "e": 3.0, "p": 0.9},
             {"w": " Og", "s": 3.3, "e": 3.95, "p": 0.9}]
    monkeypatch.setattr(E, "speech_holes", lambda speech, words, m=0.6: [(1.6, 4.0)])
    monkeypatch.setattr(eng, "listen_array", lambda *a: [dict(w) for w in heard], raising=False)
    import faster_whisper.vad as V
    monkeypatch.setattr(V, "get_speech_timestamps", lambda *a, **k: [])
    got = eng._rescue(None, np.zeros(16000 * 6, dtype=np.float32), main, "no", None, threading.Event())
    assert [w["w"].strip() for w in got] == ["Vi", "venter."]
