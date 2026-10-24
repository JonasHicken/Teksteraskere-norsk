# Teksting

**Norwegian subtitles for video, transcribed and proofread on your own Windows PC.**

A friend of mine subtitles corporate videos for a company's website. He had a cumbersome workflow in Adobe
Premiere Pro, which didn't have good AI transcription for Norwegian. Teksting writes the first draft with a
speech model based on Whisper, trained by the National Library of Norway, and gives him an editor built only
for checking it. The goal is under 3 minutes of human work per minute of video, and much faster than that
over time.

Everything runs locally. No video or audio leaves the machine, and no cloud service is involved.

![The proofreading editor](docs/editor.png)

<!-- TODO: add the measured result from real videos here, e.g. "a 10-minute video: X h by hand -> Y min with
Teksting". The Videoer page records work time per video. -->

## How it was built

I built Teksting with an AI coding agent ([Claude Code](https://claude.com/claude-code)), and the commit
history says so. My part was the product work:

- **Turning a real workflow into requirements.** Watching how subtitles are made today, what the end user
  delivers (SRT files), and what slows him down.
- **Setting the priorities that decide every trade-off.** Accuracy beats speed, always. Proofreading speed
  comes next. Features he won't use get no further investment.
- **Testing on real videos and feeding back what failed.** One example: the model once skipped a clearly
  spoken sentence. That led to the re-listening pass described below.
- **Insisting on measurements before changes.** Every performance change below was measured before and after.
  Ideas that didn't pay off were dropped and written down, with the numbers.

[`CLAUDE.md`](CLAUDE.md) is the project's working memory: decisions, measurements, rejected options and open
questions. It is kept up to date so that any session, human or AI, can pick up the work.

## What it does

- **Transcription queue.** Add any number of videos. They are transcribed in the background, shortest first,
  so the first ones are ready to proofread while the long ones run.
- **Accuracy first.** The large [NB-Whisper](https://huggingface.co/NbAiLab) model (from the National Library of
  Norway) runs with beam search and word timestamps. Two extra passes catch errors:
  - **Re-listening pass.** Stretches that contain sound but got no text are transcribed again. The result is
    only kept if it passes hallucination checks.
  - **Double-check.** A second, smaller model transcribes the video again, and every place where the two
    models disagree is flagged for a human to listen to.
- **Subtitle rules.** Max 2 lines of about 42 characters, 1–7 s on screen, max 17 characters per second, and
  a minimum gap between subtitles. Line breaks avoid ending on weak words. The 42 is a soft limit: a line may
  run a few characters over when that keeps a sentence together, so a sentence's last word is never pushed
  alone into the next subtitle. All of these can be changed in the settings.
- **Says what was said.** Abbreviations are written out in full ("f.eks." becomes "for eksempel"), in
  Bokmål or Nynorsk.
- **An editor built for proofreading.**
  - **It shows only what needs a look:** words the model was unsure of, spelling, places where the models
    disagree, and rule breaks.
  - **Fast listening:** replay a subtitle, Ctrl+click a single word to hear it, and follow the highlighted word
    as it is spoken.
  - **Keyboard first:** approve with Enter and move on; there are shortcuts for everything.
- **Learns from corrections.** A correction made in two videos is applied automatically to new ones.
- **Measures itself.** It records work time per minute of video.

## Engineering decisions, with numbers

All measured on the target machine, a laptop with a 6-core Ryzen 5 and no GPU.

| Problem | What was done | Result |
|---|---|---|
| Transcription is slow on a CPU | Use exactly one thread per physical core (hyper-threads were slower). Keep the models loaded while the queue has work. | 80 s → 60 s per minute of speech, identical text. No 20 s reload between videos. |
| Faster batched decoding was available | Measured it: only ~10 % faster, and 5 % of the words changed. | **Rejected.** Accuracy comes first. |
| The editor is idle while the double-check runs | Open the video for proofreading as soon as the main model is done. The double-check's hints appear in the open editor when they arrive. | Proofreading can start ~40 % sooner per video. The subtitles are identical. |
| 3.2 GB of RAM while proofreading | The editor needs no model, so models are freed 60 s after the queue empties. Polling slows down when idle, and the editor's render loop sleeps when nothing moves. | ~1.2 GB while proofreading |
| 3 s from click to any window | A plain Win32 window (ctypes, no imports) shows at once. The real WebView2 window replaces it on the same pixels. | First window after 0.25 s |
| App slow to appear after the loading screen | Profiling showed the spell-check dictionary (10 s of pure Python) was starving the web server. It now loads after the app has appeared. | App ready 9.4 s → 5.1 s after launch |
| Typing lagged in long videos | No forced layout per keystroke, and subtitles that are off screen are skipped. | Typing 3× faster |
| A company PC blocked the installer's Python launcher | Dropped the virtual environment and installed the packages into a portable Python inside the app folder. | Nothing is written outside the app folder |

## How it's built

A small Python backend and a plain JavaScript front end, with no build step and no database.

| Part | |
|---|---|
| `server.py` | FastAPI app: the API, the transcription queue (`Worker`), the burn-in queue (`Exporter`), progress and time estimates, the app window |
| `tekst/engine.py` | Model download and transcription with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), the re-listening pass, waveform data |
| `tekst/segment.py` | Timed words → subtitles: filler removal, dynamic-programming segmentation with break costs, line splitting, timing rules, SRT output |
| `tekst/compare.py` | Where the main and the fast model disagree |
| `tekst/learn.py` | Learning word corrections across videos |
| `tekst/spell.py` | Norwegian spell check (LibreOffice dictionaries via [spylls](https://github.com/zverok/spylls)) |
| `tekst/store.py` | Projects, settings and glossary as JSON files under `data\` |
| `tekst/launch.py`, `tekst/splash.py` | The app window ([pywebview](https://pywebview.flowrl.com/) on WebView2), the instant stand-in window and the loading screen |
| `tekst/burn.py` | Optional burned-in subtitles (Pillow + ffmpeg), hidden by default |
| `static/` | The single-page front end: `app.js` (video list, settings), `editor.js` (the editor), `i18n.js` (Norwegian and English), `style.css` |
| `tests/` | pytest suite: segmentation and SRT format, learning, comparison, storage, and the API end to end with fake transcription |

## Running it

You need Windows 10 or 11, a reasonably recent CPU (no GPU needed) and about 10 GB of free disk space.

**As a user:**
1. Double-click `start.bat`. The first start installs [uv](https://docs.astral.sh/uv/), Python 3.12 and the
   packages into `runtime\`. This takes a few minutes.
2. It creates a "Teksting" shortcut on the desktop and in the Start menu. Use that shortcut from then on.
3. The first video downloads the speech model (6.2 GB).

The user guide is in Norwegian: [`LES MEG.txt`](LES%20MEG.txt).

**As a developer:**

```bat
:: real models (http://127.0.0.1:8765)
runtime\python\cpython-3.12*\python.exe server.py

:: fake transcription, no models needed, separate data folder (http://127.0.0.1:8766)
dev\run_fake.bat

:: tests (pytest with the app's own Python; the API tests use fake transcription and finish in seconds)
dev\test.bat
```

Without `start.bat`: install `requirements.txt` and `requirements-dev.txt` into a Python 3.12, then run
`python server.py` or `pytest`.

Useful environment variables:
- `TEKSTING_FAKE=1`: fake transcription, no models needed.
- `TEKSTING_DATA`: the data folder (default `data\`).
- `TEKSTING_PORT`: the port (default 8765).
- `TEKSTING_NO_BROWSER=1`: start the server without opening a window.

`dev\pack.ps1` builds the zip that is handed to users. It contains only the code, not `data\` or `runtime\`.

## Limits

- Windows only.
- Built for Norwegian (Bokmål and Nynorsk).
- A whole job takes about 1.7× the video's length on a 6-core laptop CPU. The main model alone takes about 1×,
  and the video can be proofread from that point.

## Credits

- Speech models: [NB-Whisper](https://huggingface.co/NbAiLab) by the National Library of Norway (Apache 2.0).
- Spell checking: the Norwegian dictionaries from [LibreOffice](https://github.com/LibreOffice/dictionaries).

## License

[MIT](LICENSE)
