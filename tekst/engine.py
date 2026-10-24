"""Model download + transcription (faster-whisper / NB-Whisper). TEKSTING_FAKE=1 simulates both."""
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

FAKE = os.environ.get("TEKSTING_FAKE") == "1"

# Sizes are the NbAiLab ct2 downloads; speed = processing time / audio length on a typical laptop CPU
MODELS = {
    "small": {"repo": "NbAiLab/nb-whisper-small", "size": 0.97e9, "speed": 0.35},
    "medium": {"repo": "NbAiLab/nb-whisper-medium", "size": 3.06e9, "speed": 0.8},
    "large": {"repo": "NbAiLab/nb-whisper-large", "size": 6.18e9, "speed": 1.35},
}
EXTRA_FILES = ["tokenizer.json", "preprocessor_config.json"]  # live outside ct2/ in the NbAiLab repos


class Cancelled(Exception):
    pass


def media_duration(path):
    try:
        import av
        with av.open(str(path)) as c:
            if c.duration:
                return c.duration / 1_000_000
            s = next((s for s in c.streams if s.type == "audio"), None)
            if s is not None and s.duration and s.time_base:
                return float(s.duration * s.time_base)
    except Exception:
        pass
    return None


PEAK_RATE = 50  # waveform values per second


def compute_peaks(path):
    """Loudness envelope (0-255, PEAK_RATE values per second) for the timeline waveform."""
    import av
    import numpy as np
    hop = 8000 // PEAK_RATE
    peaks, carry = [], np.zeros(0, dtype=np.int32)
    with av.open(str(path)) as c:
        s = next((s for s in c.streams if s.type == "audio"), None)
        if s is None:
            return b""
        res = av.AudioResampler(format="s16", layout="mono", rate=8000)

        def feed(frames):
            nonlocal carry
            for f in frames:
                a = np.abs(f.to_ndarray().reshape(-1).astype(np.int32))
                a = np.concatenate([carry, a])
                n = len(a) // hop
                if n:
                    peaks.append(a[: n * hop].reshape(n, hop).max(axis=1))
                carry = a[n * hop:]

        for frame in c.decode(s):
            feed(res.resample(frame))
        try:
            feed(res.resample(None))
        except Exception:
            pass
    if not peaks:
        return b""
    p = np.concatenate(peaks).astype(np.float32)
    ref = max(float(np.percentile(p, 99.5)), 1.0)
    return np.clip(np.sqrt(p / ref) * 255, 0, 255).astype(np.uint8).tobytes()


def peaks_from_audio(audio, sr=16000):
    """Same envelope as compute_peaks, from audio already in memory (saves decoding the file again)."""
    import numpy as np
    hop = sr // PEAK_RATE
    n = len(audio) // hop
    if not n:
        return b""
    p = np.abs(audio[: n * hop]).reshape(n, hop).max(axis=1).astype(np.float32)
    ref = max(float(np.percentile(p, 99.5)), 1e-9)
    return np.clip(np.sqrt(p / ref) * 255, 0, 255).astype(np.uint8).tobytes()


def physical_cores():
    """Physical CPU cores. Whisper runs ~25 % faster on 6 than on its default 4 threads (Ryzen 5 5625U),
    while extra hyper-threads make it slower."""
    n = 0
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class INFO(ctypes.Structure):  # SYSTEM_LOGICAL_PROCESSOR_INFORMATION
                _fields_ = [("mask", ctypes.c_size_t), ("rel", wintypes.DWORD), ("pad", ctypes.c_ubyte * 20)]

            size = wintypes.DWORD(0)
            ctypes.windll.kernel32.GetLogicalProcessorInformation(None, ctypes.byref(size))
            buf = (INFO * (size.value // ctypes.sizeof(INFO)))()
            if ctypes.windll.kernel32.GetLogicalProcessorInformation(buf, ctypes.byref(size)):
                n = sum(1 for i in buf if i.rel == 0)  # RelationProcessorCore
        except Exception:
            n = 0
    if not n:
        n = max(1, (os.cpu_count() or 8) // 2)
    return max(4, min(n, 8))


def _dir_size(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class Engine:
    def __init__(self, models_dir):
        self.dir = Path(models_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._loaded = {}  # name -> model; large + small both stay loaded (~2 GB RAM), so a queue
        self.lock = threading.Lock()  # of videos doesn't reload the large model for every video
        self._audio = (None, None)  # (path, 16 kHz audio) of the video being transcribed
        self._dl_locks = {n: threading.Lock() for n in MODELS}  # one download per model at a time

    def model_dir(self, name):
        return self.dir / name

    def is_ready(self, name):
        d = self.model_dir(name)
        return (d / "model.bin").exists() and (d / "config.json").exists()

    def status(self):
        return {n: {"ready": self.is_ready(n), "loaded": n in self._loaded, "size": m["size"], "speed": m["speed"]}
                for n, m in MODELS.items()}

    def delete(self, name):
        with self.lock:
            self._loaded.pop(name, None)
            shutil.rmtree(self.model_dir(name), ignore_errors=True)

    def download(self, name, on_progress, stop):
        """Fetch the ready-made CTranslate2 model (only the files we need). A second call for the same model
        (Settings "download" while a job starts) waits for the first instead of writing the same folder."""
        with self._dl_locks[name]:
            if not self.is_ready(name):
                self._download(name, on_progress, stop)

    def _download(self, name, on_progress, stop):
        info = MODELS[name]
        tmp = self.dir / f".{name}-download"
        tmp.mkdir(exist_ok=True)
        done = threading.Event()

        def watch():
            while not done.wait(0.7):
                on_progress(min(0.999, _dir_size(tmp) / info["size"]))

        threading.Thread(target=watch, daemon=True).start()
        try:
            if FAKE:
                for k in range(10):
                    if stop.is_set():
                        raise Cancelled()
                    (tmp / f"chunk{k}").write_bytes(b"x" * int(info["size"] / 1e6))
                    time.sleep(0.15)
                    on_progress((k + 1) / 10)
                (tmp / "ct2").mkdir(exist_ok=True)
                (tmp / "ct2" / "model.bin").write_bytes(b"fake")
                (tmp / "ct2" / "config.json").write_text("{}")
            else:
                from huggingface_hub import snapshot_download
                snapshot_download(info["repo"], allow_patterns=["ct2/*"] + EXTRA_FILES, local_dir=str(tmp))
            target = self.model_dir(name)
            shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(tmp / "ct2"), str(target))
            for f in EXTRA_FILES:
                if (tmp / f).exists():
                    shutil.copy2(tmp / f, target / f)
            shutil.rmtree(tmp, ignore_errors=True)
        finally:
            done.set()

    def _model(self, name):
        with self.lock:
            if name not in self._loaded:
                if FAKE:
                    m = "fake"
                else:
                    from faster_whisper import WhisperModel
                    m = WhisperModel(str(self.model_dir(name)), device="cpu", compute_type="int8",
                                     cpu_threads=physical_cores())
                self._loaded[name] = m
            return self._loaded[name]

    def is_loaded(self, name):
        return name in self._loaded


    def unload(self, keep=()):
        """Free every loaded model not in `keep` (large holds ~1.5 GB of RAM, small ~0.26 GB). A transcription
        already using one keeps its own reference, so this never pulls a model out from under it."""
        with self.lock:
            gone = [n for n in self._loaded if n not in keep]
            for n in gone:
                del self._loaded[n]
        if gone:
            import gc
            gc.collect()
        return gone

    def audio(self, path):
        """16 kHz audio of the file, decoded once per job (main model, double-check and waveform share it)."""
        if self._audio[0] != str(path):
            from faster_whisper.audio import decode_audio
            self._audio = (None, None)
            self._audio = (str(path), decode_audio(str(path), sampling_rate=SR))
        return self._audio[1]

    def cached_audio(self, path):
        return self._audio[1] if self._audio[0] == str(path) else None

    def drop_audio(self):
        self._audio = (None, None)

    def plan(self, name, dur, rescue=False, loaded=None):
        """Expected seconds for each phase of transcribe() (before any real measurement)."""
        dur = dur or 600.0
        if FAKE:
            out = [("model", 0.1), ("audio", 0.4), ("vad", 0.6), ("decode", 12.0)]
            return [x for x in out if x[0] != "model"] + ([("rescue", 0.6)] if rescue else [])
        speed = MODELS[name]["speed"]
        out = []
        if not (self.is_loaded(name) if loaded is None else loaded):
            out.append(("model", {"large": 25.0, "medium": 12.0}.get(name, 5.0)))
        out += [("audio", dur / 120 + 1), ("vad", dur / 90 + 1), ("decode", dur * speed)]
        if rescue:
            out.append(("rescue", dur * speed * 0.15 + 5))  # each re-heard stretch costs a 30 s window
        return out

    def transcribe(self, name, path, language, prompt, on_progress, stop, rescue=False):
        """Return word list [{"w","s","e","p"}] for the media file.

        on_progress(p, phase, cap=None): p = 0-1 within the phase; phases in order:
        "model" (loading), "audio" (reading the file), "vad" (finding speech), "decode", "rescue".
        cap = how far p can get before the next report (lets the UI move smoothly in between).

        rescue=True: afterwards, re-listen (without the voice filter) to every stretch of 1.5 s+
        that got no text but does contain sound. Recovered words are marked "r": 1.
        """
        if not self.is_loaded(name):
            on_progress(0.0, "model")
        model = self._model(name)
        if FAKE:
            words = _fake_words(path, on_progress, stop, variant=(name == "small"), drop=rescue)
            if rescue:
                on_progress(0.0, "rescue")
                time.sleep(0.6)
            return sorted(words + (_fake_rescue(words) if rescue else []), key=lambda w: w["s"])
        on_progress(0.0, "audio")
        audio = self.audio(path)
        dur = len(audio) / SR
        on_progress(0.0, "vad")
        segs, info = model.transcribe(
            audio, language=language, task="transcribe", beam_size=5, word_timestamps=True,
            vad_filter=True, vad_parameters=VAD, condition_on_previous_text=False, hotwords=prompt or None,
        )
        ahead = lambda t: min(1.0, (t + 40.0) / dur) if dur else None  # noqa: E731  ~one 30 s window
        on_progress(0.0, "decode", ahead(0.0))
        words = []
        for s in segs:
            if stop.is_set():
                raise Cancelled()
            words += _real([_w(w) for w in (s.words or [])])
            if dur:
                on_progress(min(1.0, s.end / dur), "decode", ahead(s.end))
        on_progress(1.0, "decode")
        if rescue:
            on_progress(0.0, "rescue")
            words = sorted(words + self._rescue(model, audio, words, language, prompt, stop, on_progress),
                           key=lambda w: w["s"])
        return words

    def _rescue(self, model, audio, words, language, prompt, stop, on_progress=None):
        """Re-listen to every stretch where the voice detector hears speech but the main pass wrote nothing.
        Each stretch is transcribed on its own (with 0.6 s around it): on a short clip the model keeps phrases
        it skipped in the long pass. Before 2026-10-24 only gaps of 1.5 s+ that looked loud were re-listened;
        on a fast debate (Jonas's test clip) that missed 7 phrases in shorter gaps ("og jeg har problemer med
        å forstå det her også.", "til staten som eier." ...) at about the same total time."""
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        dur = len(audio) / SR
        speech = [(t["start"] / SR, t["end"] / SR) for t in get_speech_timestamps(audio, VadOptions(**RESCUE_VAD))]
        holes = speech_holes(speech, words, RESCUE_MIN)
        have = sorted(words, key=lambda w: w["s"])
        found = []
        for i, (a, b) in enumerate(holes):
            if stop.is_set():
                raise Cancelled()
            if on_progress:
                on_progress(i / len(holes), "rescue", (i + 1) / len(holes))
            c0, c1 = max(0.0, a - 0.6), min(dur, b + 0.6)
            cand = self.listen_array(model, audio[int(c0 * SR):int(c1 * SR)], c0, language, prompt)
            # only words inside the stretch, and none that repeats a word the main pass already has at its edge
            cand = [w for w in cand if w["s"] >= a - 0.2 and w["e"] <= b + 0.2 and not _overlaps(have, w)]
            # the clip's first/last word heard again right next to the same word of the main pass ("Og Og")
            before = next((w for w in reversed(have) if w["e"] <= a + 0.05), None)
            after = next((w for w in have if w["s"] >= b - 0.05), None)
            if cand and after and _same(cand[-1], after):
                cand.pop()
            if cand and before and _same(cand[0], before):
                cand.pop(0)
            if not cand:
                continue
            text = " ".join(w["w"] for w in cand)
            if HALLU.search(text) or sum(w["p"] for w in cand) / len(cand) < 0.45:
                continue
            for w in cand:
                w["r"] = 1
            found += cand
        return found

    def listen_array(self, model, clip, offset, language, prompt):
        segs, _ = model.transcribe(
            clip, language=language, task="transcribe", beam_size=5, word_timestamps=True,
            vad_filter=False, condition_on_previous_text=False, hotwords=prompt or None,
        )
        out = []
        for s in segs:
            for d in _real([_w(w) for w in s.words or []]):
                d["s"] = round(d["s"] + offset, 3)
                d["e"] = round(d["e"] + offset, 3)
                out.append(d)
        return out



SR = 16000
# Re-listening: the voice detector finds speech; stretches of it with no text, at least RESCUE_MIN s long, are
# transcribed again (measured on a fast debate clip, 2026-10-24: 0.6 s / threshold 0.35 recovered the most;
# 0.4 s / 0.25 found only extra one-word scraps).
RESCUE_VAD = {"threshold": 0.35, "min_silence_duration_ms": 300, "speech_pad_ms": 100}
RESCUE_MIN = 0.6


def speech_holes(speech, words, min_len=RESCUE_MIN):
    """Stretches of speech [(start, end)] where no word was written, at least min_len s long."""
    import bisect
    ws = sorted(words, key=lambda w: w["s"])
    starts = [w["s"] for w in ws]
    holes = []
    for s, e in speech:
        k = bisect.bisect_left(starts, s)
        while k > 0 and ws[k - 1]["e"] > s:  # a word that began before the stretch and runs into it
            k -= 1
        cur = s
        while k < len(ws) and ws[k]["s"] < e:
            w = ws[k]
            if w["e"] > cur:
                if w["s"] - cur >= min_len:
                    holes.append((cur, w["s"]))
                cur = max(cur, w["e"])
            k += 1
        if e - cur >= min_len:
            holes.append((cur, e))
    return holes


def _same(a, b):
    return re.sub(r"\W+", "", a["w"].lower()) == re.sub(r"\W+", "", b["w"].lower())


def _overlaps(ws, w):
    """Does word w lie mostly on top of a word in ws (sorted by start)? Then it is the same word heard again."""
    import bisect
    k = bisect.bisect_left([x["s"] for x in ws], w["e"])
    for x in ws[max(0, k - 3):k]:
        shared = min(x["e"], w["e"]) - max(x["s"], w["s"])
        if shared > 0.5 * max(0.01, w["e"] - w["s"]):
            return True
    return False
# Gentler than faster-whisper's defaults: less risk of cutting quiet or overlapping speech
VAD = {"threshold": 0.35, "min_silence_duration_ms": 700, "speech_pad_ms": 500}
# Typical Whisper "hallucinations" on silence/music in Norwegian training data
HALLU = re.compile(r"(teksting|tekstet|undertekst\w*|oversatt)\s+(av|:)|takk for at (du|dere) (så|har sett|fulgte|lyttet)"
                   r"|abonner|nrk\s*tekst|www\.|\.no\b", re.I)


def _w(w):
    return {"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3)}


MARKER_RE = re.compile(r"[<>|]|nocaptions|nospeech", re.I)  # same as segment.MARKER_RE


def _real(words):
    """Without the pieces of "<|nocaptions|>" the model writes as text where it gives up on a stretch."""
    return [w for w in words if not MARKER_RE.search(w["w"])]


FAKE_TEXT = (
    "Hei og velkommen til denne presentasjonen. eh I dag skal vi snakke om hvordan Telenor Norge "
    "har jobbet med bærekraft de siste fem årene, og hva vi har lært underveis. Ehm for det første "
    "er det viktig å forstå at utslippene våre har gått ned med 23 prosent siden 2019. Mm det er et "
    "resultat av mange små og store endringer i hele organisasjonen, som vi er veldig stolte av. Ja. "
    "Men vi er ikke ferdige. Neste år skal vi investere over to hundre millioner kroner i nye løsninger "
    "for energieffektivisering i alle datasentrene våre, og vi håper at flere vil ta del i dette arbeidet. "
    "Jeg tror at dette er noe vi alle kan bidra til. Takk for oppmerksomheten."
).split()


FAKE_SWAPS = {"forstå": "forstår", "investere": "investerer", "Telenor": "Telenord", "lært": "lært oss"}


def _fake_rescue(words):
    return [dict(w, r=1) for w in _FAKE_DROPPED]


_FAKE_DROPPED = []


def _fake_words(path, on_progress, stop, variant=False, drop=False):
    dur = media_duration(path) or 60.0
    t, k, words = 0.6, 0, []
    while t < dur - 1:
        tok = FAKE_TEXT[k % len(FAKE_TEXT)]
        if variant:
            core = tok.strip(".,")
            if core in FAKE_SWAPS:
                tok = tok.replace(core, FAKE_SWAPS[core])
        d = 0.06 * len(tok) + 0.12
        words.append({"w": " " + tok, "s": round(t, 3), "e": round(min(t + d, dur), 3),
                      "p": 0.4 if tok in ("Telenor", "bærekraft") else 0.95})
        t += d + 0.05 + (0.7 if tok.endswith(".") else 0.25 if tok.endswith(",") else 0)
        if k % len(FAKE_TEXT) == len(FAKE_TEXT) - 1:
            t += 4.0  # a long pause now and then
        k += 1
    if drop:  # simulate the model skipping one sentence ("Ja. Men vi er ikke ferdige.")
        keep, gone, inside = [], [], False
        for w in words:
            core = w["w"].strip()
            if core == "Ja." and not gone:
                inside = True
            if inside:
                gone.append(w)
                if core.endswith("ferdige."):
                    inside = False
                continue
            keep.append(w)
        _FAKE_DROPPED[:] = gone
        words = keep
    # mimic the real engine: read audio, find speech, then text arrives in bursts (one per window)
    for ph, sec in (("audio", 0.4), ("vad", 0.6)):
        on_progress(0.0, ph)
        time.sleep(sec)
    steps = 6
    on_progress(0.0, "decode", 1 / steps)
    for i in range(steps):
        for _ in range(8):
            if stop.is_set():
                raise Cancelled()
            time.sleep(0.25)
        on_progress((i + 1) / steps, "decode", min(1.0, (i + 2) / steps))
    return words
