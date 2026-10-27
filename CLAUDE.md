# Teksting — project memory for Claude Code

Local Windows app that turns Norwegian corporate videos (10–60 min) into publication-quality SRT subtitles,
plus an editor to proofread them against the video. Built in a claude.ai session (Oct 2026), moved to
Claude Code on 2026-10-08. Read this fully before changing anything.

## The people and the goal
- **Owner**: product decisions, requirements and testing; builds this with Claude Code. Explain technical
  steps and commands plainly, prefer doing over telling, keep answers concise, challenge ideas rather than
  agreeing, and use Socratic questions when explaining something new.
- **End user**: subtitles corporate videos for a big company's website. Today they download videos
  from Vimeo, write captions in Adobe Premiere Pro, and deliver **SRT** files (confirmed 2026-10-09: no CSV needed).
- **Goal**: under 3 min of human work per 1 min of video (was 6 until 2026-10-15), and much faster than that
  over time.
  The app measures this ("Arbeidstid" per video, average vs goal on the Videoer page).
- **Hardware**: laptop CPU only. Transcribe overnight, proofread by day.
- **Promise shown in the app**: everything runs locally, nothing is uploaded. Don't add cloud services without
  asking the owner (a cloud AI proofreader was discussed and rejected for this reason).

## Priorities (2026-10-09) — use these to decide every trade-off
1. **Transcription accuracy beats speed, always.** Never trade accuracy for speed (no smaller beam, no
   batched decoding, no partial double-check). Speed-ups are welcome only when output stays identical.
2. **Proofreading editor: usability, UI functionality and speed** — this is where the human minutes go.
- Burn-in is low priority: the end user won't use it (keep it working, don't invest in it).

## Subtitle rules (Netflix-style, Norwegian)
42 chars/line, max 2 lines, 1–7 s per cue, max 17 chars/s, ≥0.08 s gap between cues, cue lingers 0.3 s after
last word, never join across a 1.2 s pause. Light editing: filler words (eh, ehm, øh, mm, hm…) removed.
Line breaks avoid ending a line on weak words (articles, prepositions, adjectives before nouns, numerals).
**End-user feedback (2026-10-24):**
- **42 is a soft limit.** `char_slack` (default 4, in Settings) lets a line run up to 46 at a cost of 2.5 per
  character over, and `orphan_cost` / `split_lines` penalise a sentence's last 1–2 words cut off into the next
  cue or line (+10 / +4), and a new sentence's first word left alone at the end (+6). On 5 realistic samples the
  old segmenter left 1 orphan, now 0 (`test_no_word_is_cut_off_from_its_sentence`). The editor flags a line as
  too long only past 42 + slack.
- **No abbreviations, ever.** `expand_abbreviations` (after `clean_words`, before segmentation, so the rules
  count the full text) writes out `ABBREV` (+ `ABBREV_NN` for nynorsk, from the project's language):
  f.eks./feks → for eksempel, bl.a., osv., dvs., ca., pga. … Also when split ("f." + "eks."). The full words
  share the abbreviation's time span; the dot stays only at a sentence end; the capital is kept. Words that are
  also real words (bla, mm, ol, st) are deliberately not in the table. Existing videos get it with
  "Bruk reglene på nytt".
- **Balanced lines and natural splits (same day, second round).** `balance_cost`: 0.6 per character of
  difference beyond 4 between the two lines (was 0.15 from 0); grammar still wins (weak-word ends +10, so
  "den nye / strategien" is not split just to even out). `MID_CLAUSE` +3 for a new subtitle with no comma
  or pause, +6 more if that subtitle is a scrap of 15 characters or less. Reading speed in `cue_cost` now
  counts the pause after the last word (`room`), as `time_cues` really shows the subtitle into it: a full
  sentence fits instead of losing its last words. Measured with a scratch harness on the samples at 3
  speech speeds, with and without pauses: mean line difference 7.7 to 6.6, worst 24 to 18, 0 orphans,
  0 weak line ends, 0 lines past 46. Every change has a test that fails when it is reverted (checked).
- **Longer line at the bottom (third round).** Line priorities in `split_lines`: keep phrases together
  (line ending on a `NO_END_STRONG` / `NO_END_MED` word +30 / +25), then the longer line at the bottom
  (`top_longer_cost`: 5 + 0.6 per character the top is longer, beyond the 4 free characters), then even
  lengths (`balance_cost`). On the samples the top line is clearly longer (more than 6) only once:
  "Vi tror at det skyldes den nye strategien / vi innførte tidlig på året.", where every bottom-heavy split
  breaks "den nye / strategien" or needs a line over 42 (the slack is for sentences, not for shape).
  `test_the_longer_line_is_the_bottom_one` checks exactly that rule.
**Editor features (2026-10-24, the owner chose 1, 2, 6, 9, 11 from a brainstorm):**
- *Speech without text*: `speech.json` per project = voice-detector regions (`Engine.speech`, saved with the job;
  `GET /api/projects/{pid}/speech` computes it for older videos, ~4 s per 5 min). The editor's `findHoles()`
  subtracts the subtitles (≥ `HOLE_MIN` 0.6 s), recomputed on every structural change; hatched red bands on the
  timeline (orange when the fast model heard words there: `disagree` entries with empty `a`), click = hear it +
  toast with "Sett inn som undertekst"/"Lag undertekst her"; Alt+T = next; count in the progress line.
- *Insert from the fast model*: a hint with empty `a` whose middle lies in a subtitle gets "Sett inn"
  (`insertExtra`: placed after the model word before it, everyday first word lowered mid-sentence via
  `lower_mid` from the server, re-wrapped if a line gets too long). Between subtitles it belongs to the band.
- *Characters per line*: `.cc` on the selected subtitle, `38/42`; orange in the soft zone, red past it.
- *Drag and drop*: `tekst/launch.py` registers a pywebview DOM `drop` handler on every page load; it gets
  `pywebviewFullPath` (a web page only gets names) and calls `server.media_paths` + `add_jobs` (a folder adds
  the media files directly inside it). The page shows a drop overlay; in a plain browser it says to use the
  button. Verified up to the drop event; a real Explorer drag was not automated.
- *Movable divider*: `.ed-split` between picture and list (`initSplit`), `--lf/--rf` fr values, remembered in
  localStorage `teksting.split`, double-click resets, arrow keys move it; list ≥ 400 px, picture ≥ 320 px.
All tunables: `tekst/segment.py` class `P`; user-editable subset in Settings → "Regler for undertekster".

## The repo is public
Everything committed (code, comments, this file, commit messages) is visible to anyone, and the `release` branch
ships straight to the end user. Keep it professional and privacy-safe: no names, employers, emails, user paths,
real transcripts or client videos; synthetic test data only; refer to "the owner" and "the end user".
Check `git diff --cached` before each commit.

## Shipping updates (since 2026-10-25)
`dev\publish.ps1` (clean tree → tests → push main + `release` branch → zip). Installed copies (`tekst/update.py`)
read the `release` sha from the GitHub API 30 s after start and every 6 h, download that commit's zip into
`data/update/ready` (only the files `dev/pack.ps1` ships, CRLF for scripts), and apply it at the next start at
the top of `server.py` (old files → `data/update/previous`), install changed requirements, then restart.
Never in a git checkout or fake mode; Settings toggle `auto_update`. Note: the restart runs the *installed*
update.py, not the new one. Verified end to end against real GitHub in plain and `--app` mode (2026-10-25).
Safety (bug check 2026-10-25): skipped while another copy runs (mutex `Local\Teksting.window.<port>`); release
read via git refs (no API limit); never backwards (compare API, best effort; undo a release with `git revert` +
publish); a version that never reaches the first `/api/state` is rolled back at the following start and its sha
goes to `data/update/skip.txt`; the app shows a one-time notice. Steps are logged to `data/teksting.log`.
**Release notes (owner's standing rule, 2026-10-27): every publish gets one.** Before running publish, add a
new entry at the top of `static/changelog.json` (`n` = previous + 1, `date` = today, then `no` and `en`, each
with a short `title` and `items` = what changed for the user, in plain bokmål and the same in English, no
internal or technical terms; the app shows the one matching its language). It is shown under
"Hva er nytt" on the Videoer page (dot until opened, `settings.seen_release`). `publish.ps1` refuses when the
top entry is not newer than the one on the `release` branch, unless run with `-NoNotes` (only when the owner
says an update should go out without notes); `tests/test_changelog.py` checks the format.

## Run it
- **Users**: double-click `start.bat` once (downloads uv → Python 3.12 → packages into `runtime\` — no venv, see below,
  creates Desktop + Start-menu shortcut "Teksting" via `lag-snarveier.ps1`), then use the shortcut
  (`Teksting.vbs` → hidden `pythonw server.py --app`).
- **Dev, real models**: `runtime\python\cpython-3.12.15-windows-x86_64-none\python.exe server.py` → http://127.0.0.1:8765
- **Dev, fake mode (no models, instant)**: `dev\run_fake.bat` → http://127.0.0.1:8766 — fake transcripts,
  fake downloads, separate data folder `dev\fakedata`. Add any short .mp4 as a video. Use this for all UI work.
  Port 8766 so it can run alongside the real app on 8765.
- Env vars: `TEKSTING_FAKE=1`, `TEKSTING_DATA` (data folder, default `data\`), `TEKSTING_PORT` (8765),
  `TEKSTING_NO_BROWSER=1`, `TEKSTING_APP=1` or `--app` (Edge/Chrome app window + auto-exit),
  `TEKSTING_IDLE_EXIT` (seconds, default 90, browser fallback only), `TEKSTING_DEBUG_PORT` (dev: Chrome DevTools
  port for the app window, e.g. 9333 → http://127.0.0.1:9333/json; drive it with a CDP script).
- Log when started from the shortcut: `data\teksting.log`.
- Build the zip for the end user: `powershell -ExecutionPolicy Bypass -File dev\pack.ps1` → `dist\Teksting.zip`
  (code only, CRLF for .bat/.vbs/.ps1/.txt; never include `data\`, `runtime\`).
  Gmail blocks this zip (it contains .bat/.vbs) — share via OneDrive link.
- `dev\run_fake.bat` and `dev\pack.ps1` were recreated in Claude Code on 2026-10-08 (the originals never left
  the claude.ai session).

## Architecture
FastAPI + uvicorn backend, vanilla-JS single-page app (no build step), files on disk as the database.

| File | What it does |
|---|---|
| `server.py` | API, background `Worker` (transcription queue, one job at a time), `Exporter` (burn-in queue), `Tracker` (phase-weighted progress + ETA), app mode (own window via pywebview/WebView2, see below; Chrome/Edge `--app` only as fallback), Windows keep-awake while busy, tkinter file picker in a subprocess (DPI-aware) |
| `tekst/engine.py` | Model download (HF `NbAiLab/nb-whisper-{small,medium,large}`, ready-made `ct2/` folders + tokenizer/preprocessor files), faster-whisper transcription, **gap rescue**, waveform peaks, fake mode |
| `tekst/segment.py` | Words → cues: filler removal, DP segmentation with break costs, line splitting, timing rules, SRT writer |
| `tekst/compare.py` | Disagreements between the main model and the fast model (double-check) |
| `tekst/learn.py` | Learns word corrections (original vs edited cues); auto-applies a rule after it's seen in ≥2 videos; user can set on/off/delete |
| `tekst/spell.py` | Hunspell nb_NO / nn_NO via spylls (LibreOffice dictionaries, downloaded on first use) |
| `tekst/burn.py` | Burned-in subtitles: Pillow renders one PNG per cue → ffmpeg overlay (imageio-ffmpeg binary), encoder fallbacks libx264 → h264_mf → libopenh264 → mpeg4. Output `<video>_tekstet.mp4` |
| `tekst/store.py` | Settings (`DEFAULT_SETTINGS`), glossary, projects under `data\projects\<id>\` |
| `static/app.js` | Router, Videoer page (queue, status, batch export, work-time stats), Settings page, toasts, tooltips (`data-tip`) |
| `static/editor.js` | Proofreading editor (class `Editor`) |
| `static/i18n.js` | All UI text, `nb` and `en`. **Every UI string goes here in both languages.** |
| `static/style.css` | Tokens at top (light + dark), later "polish v6" block overrides; dark "studio" editor left pane |

Project folder files: `meta.json`, `words.jsonl` (word timings), `cues.json` (current), `cues_orig.json`
(as produced, for learning), `disagree.json`, `rescued.json`, `autofix.json`, `peaks.bin` (uint8, 50/s).

### App window (app mode, since 2026-10-08)
`tekst/launch.py` (server.py hands over at the top, before importing FastAPI): pywebview (`gui="edgechromium"`,
WebView2 is built into Windows) owns the main thread and opens at once with `static/loading.html`; a thread
imports `server` and runs uvicorn beside it (`serve_in_background`). The loading page (a small typewriter
typing "Teksting" with a yellow subtitle bar, app tokens, light/dark) pings `/api/ping` (fetch no-cors) and
switches to the app itself; once ready it finishes the word fast (no waiting on the animation).
Fixed timeline (constants at the top of the script): "Raskere teksting" fully typed at
(DONE_MS; 1.25 s since 2026-10-15), fade 1.3–1.55 s (SHOW_MS, FADE_MS; was 2.7–3.0 s until 2026-10-15) after the real window shows, later only if the server isn't ready.
A more elaborate intro was built and dropped on 2026-10-09 in favour of a minimal one.
`Teksting.vbs` skips the uv package check unless requirements.txt differs from `runtime\requirements.installed`
(written by start.bat / the vbs): right after a reboot that no-op check took 7.8 s. Process AppUserModelID `Teksting.Teksting` = the ID that
`lag-snarveier.ps1` writes on the shortcuts → one taskbar button with the Teksting icon, and pinning works.
(Replaced the Chrome/Edge `--app` window: it showed the Chrome icon and its pin just opened Chrome.)
- Closing the window when idle quits at once. Closing while a job runs only **hides** it; the watchdog quits
  when the last job is done. Starting again (shortcut) while running → `POST /api/show` brings the window back.
- `Teksting.vbs` must start pythonw with window style 1, not 0: Windows applies the "hidden" start to the
  first window. `launch.py` also re-shows on the `shown` event, as a safety net.
- Startup timings go to the log ("stand-in window after", "window shown after", "server ready after").
  Two traps found: the nb dictionary takes ~10 s of pure Python to load (now `warm_speller`, after the
  window is up), and on Windows a connect to a closed port takes ~2 s (`port_in_use`, 0.3 s timeout).
- **Instant stand-in window (2026-10-15: the time from clicking the icon until a window
  appears was too long)**: `tekst/splash.py` is the first thing app mode runs (server.py imports only os/sys/time before it).
  A plain Win32 window (ctypes, same colour/icon/title/dark title bar) shows 0.25 s after Python starts; the
  real window replaces it in the same spot ~2 s later (`on_shown` closes it). Measured click→first window
  3.05 s → 0.25 s; real window 3.05 → ~2.2 s; server answers 3.8 → ~2.6 s.
  - Same spot: `splash.layout()` gives one rectangle for both (logical for pywebview `x/y/width/height`,
    physical = int(v × scale) like WinForms). 1440×900 but capped to the work area — before, on the dev
    1920×1080 @125 % laptop, the window was 1800×1125 (taller than the 1020 px above the taskbar) and at
    Windows' cascading default spot. The log line "stand-in (…) -> window (…)" says "MOVED" if they differ.
  - "Already running" is a named mutex `Local\Teksting.window.<port>` (instant). The two 0.3 s port checks
    per start are gone (0.6 s); the server checks its port with a bind test (`port_free`) and
    `wait_until_ready` asks uvicorn's `started` flag. Second start → `/api/show` (retries ~10 s), no window.
  - **Dictionary warm-up after the app page (2026-10-15)**: `warm_speller` used to start when the server
    answered. Its ~10 s of pure Python starved the web server: the loading screen's first ping took ~3 s and the
    app's files another ~3 s. It now waits for the first `/api/state` (`APP_LOADED`, max 30 s): app page loaded
    9.4 s → 5.1 s after launch (measured with `TEKSTING_DEBUG_PORT`, which adds ~0.5 s). Shortening the loading
    animation alone only gained 0.4 s — the server was the bottleneck.
  - `TEKSTING_NO_SPLASH=1` turns the stand-in off. Screen grabs (PIL ImageGrab) don't capture WebView2
    content: check the page through `TEKSTING_DEBUG_PORT` + CDP instead.
- WebView2 with pywebview's defaults: no browser right-click menu, no browser shortcuts (Ctrl+F reaches the
  app). Downloads ("Last ned SRT") show a Save dialog (`ALLOW_DOWNLOADS`).

### Transcription pipeline (Worker.process)
1. Ensure models downloaded (main + `small` if double-check is on).
2. `engine.transcribe(main, rescue=True)`: decode audio → faster-whisper (int8 CPU, beam 5, word timestamps,
   `vad_filter` with VAD = threshold 0.35 / min_silence 700 / pad 500, `condition_on_previous_text=False`,
   glossary + learned words passed as `hotwords`).
3. **Gap rescue** (`Engine._rescue`, rewritten 2026-10-24): Silero VAD (`RESCUE_VAD`, threshold 0.35) finds
   speech; every stretch of it with no word, ≥0.6 s (`speech_holes`), is transcribed again on its own (±0.6 s,
   no VAD); kept only if no hallucination pattern (`HALLU`) and mean word prob ≥0.45, without words lying on an
   existing word (`_overlaps`) or repeating the neighbouring word at the edge ("Og Og", `_same`). Marked
   `"r": 1`, flagged in the editor. Before: only gaps ≥1.5 s that looked loud.
   **Measured on the owner's fast debate clip (4:41, 2026-10-24; "it skipped a lot of dialogue")**: the main pass
   drops many phrases (NB-Whisper learned from condensed TV subtitles; it even writes "<|nocaptions|>" as text
   for a stretch). The old rescue got most of them back; the new one recovered 7 more phrases in 1.0-1.3 s gaps
   ("til staten som eier.", "Da tror jeg sånne", "og jeg har problemer med å forstå det her" ...), re-listened
   words 141 -> 170, at about the same time (rescue ~8 min on that clip: each stretch costs a 30 s window).
   Ruled out by measurement: `no_speech_threshold=None` (no extra speech, one more nocaptions segment); threshold
   0.25 / 0.4 s stretches (only one-word scraps); the verbatim model (lowercase, no punctuation; owner: no "eh"s).
   Still missed: overlapping speakers ("Jeg syns jo at", "på formuen sin, og vi"). A re-heard stretch can start
   with a capital mid-sentence when its first word is not in `LOWER_MID` ("er Lønninga på et nivå").
   The `<|nocaptions|>` pieces (`| > < |nocaptions`) are dropped in the engine (`_real`) and in `clean_words`.
   The time estimate measures re-listening speed too (`Tracker`); its plan is `dur*speed*0.15+5`.
4. `make_cues` → learned rules applied (`autofix.json`) → saved.
5. Waveform peaks. Status `done` — **the video can be proofread from here** (2026-10-15).
6. Double-check (`Worker.double_check`, after `done`): `small` model transcribes again; disagreements (ignoring
   spacing and non-words) → `disagree.json`. Meta `checking` (bool) / `check` (0–1) while it runs; status stays
   `done`. The job list says "Dobbeltsjekker i bakgrunnen: n %"; an open editor shows it in its queue line and,
   when `checking` turns false, `loadHints()` fetches the hints, refills the rows (text and focus untouched)
   and toasts. Undo keeps hints that arrived later (`hv` in snapshots). It was ~40 % of a job (large ≈ 1×,
   whole job ≈ 1.7× real time), so a video opens that much sooner; the subtitles are identical. Cancelled
   (delete) or cut off (app closed: `start_services` clears `checking`) → the video just has no hints. Retried
   meanwhile → the hints are dropped (they belong to the old transcript). `took`/`expected` exclude the check.
Progress: engine reports `(p, phase, cap)` per phase (model/audio/vad/decode/rescue); `Tracker` maps phases
to time-weighted ranges, measures real speed during decode, sends `rate`/`cap`/`pt`; the UI extrapolates every
250 ms so the bar moves smoothly. `time_scale()` learns this PC's speed from finished jobs (`took/expected`).

### Performance (measured 2026-10-08, Ryzen 5 5625U, 6 cores / 12 threads)
- `cpu_threads=physical_cores()` (4–8): large model 80.5 s → 59.9 s per 60 s of speech vs the default 4
  threads, identical text. 12 threads (hyper-threads) is *slower*. Small model gains nothing.
- Large ≈ 1× real time on this PC; a whole job (large + rescue + small double-check) ≈ 1.7× real time.
- `Engine._loaded` keeps large + small loaded while the queue has work: no reload per video (−20 s/video).
- RAM (measured 2026-10-09): large 1.53 GB (loads in ~5 s warm), small 0.26 GB (~1 s), speller 0.53 GB
  (~12 s, pure-Python spylls; kept — dropping it would cost 12 s per editor open), rest ~0.1 GB. Window
  (WebView2) ~0.7 GB. Idle with both models loaded the app was ~3.2 GB.
- Freeing idle models (`Worker.free_idle_models`): both models are freed `TEKSTING_IDLE_FREE` (60 s) after
  the last job once the queue is empty. Only transcription uses a model: the editor has no model features
  (decided 2026-10-09: when proofreading, a human ear beats the model), so proofreading runs at ~1.3 GB.
- Polling: 1 s while anything runs/queues/exports/downloads, 3 s idle, 10 s while the window is hidden
  (must stay < 90 s: the browser-mode watchdog quits after 90 s without a poll). `/api/downloads` only on the
  settings page or during a download. Editor `loop()` sleeps after ~30 still frames while paused; video
  events (`play`, `seeking`, `timeupdate` ...) call `wake()`.
- `Engine.audio()` decodes each file once per job (bit-identical to the old per-step decode, verified);
  waveform via `peaks_from_audio` (correlation 0.999 with `compute_peaks`, which is still the fallback).
- `Store` caches meta.json in memory (all writes go through it): `/api/state` with 60 videos was 71 ms,
  polled every second. Don't edit meta.json by hand while the app runs.

### Editor: background queue (2026-10-09)
`Editor.syncQueue` (called from every poll): "• Transkriberer <name> · 38 % · +2 i kø" in the editor
header (link back to the list), and a toast "«name» er klar til korrektur" + "Åpne" when a queued video
finishes. Uses `live()`/`RUNNING` from app.js (classic scripts share globals).

### Editor layout (2026-10-09)
- SRT only by default: setting `burn_tools` (off) hides Stil, Flytt opp, burned-in export and the batch
  "Lag videoer med tekst"; the header then has one "Lagre SRT" button (save next to the video) and
  "Last ned SRT" sits in ⋯. With the setting on, everything is back as before.
- Selected cue: one tool row — "Hør på nytt" (emphasised) | icons for wrap / split / merge / delete
  (labels in aria-label + tooltip with the shortcut) | undo, Godkjenn. Tool buttons cancel mousedown so the
  caret stays in the text.
- Denser cards; approved cues (not selected) shrink to their first line, muted, chips hidden.
- Chip colours: red = breaks a rule, orange = listen and check (unsure, alternative, recovered, unknown
  word, silent gap), blue = information (timing advice, automatic fixes). Shorter chip texts.
- Shortcut card is a popup above the keyboard button (closes on outside click / Esc); the left side no
  longer scrolls.
- Spoken-word highlight: `highlightWord` (from `loop()`) marks the word being spoken in the playing cue via a
  mirror div (`.ta-wrap .hl`) under the transparent textarea; `cueWords`/`tokenFor` map model words to the
  edited text (same matching as Ctrl+click). The mark stays on the last word when paused, clears on typing.

### Editor speed with long videos (2026-10-09)
Test: 60-min fake project (silent `anullsrc` audio, 683 cues), timings via CDP in the real window.
Typing a key 77 → 23 ms, next cue 72 → 17 ms, open 602 → 252 ms. Causes: `videoBox()` read
`stage.clientWidth` after DOM changes → forced layout of the whole page on every key (now cached via
ResizeObserver); off-screen cues laid out anyway (now `content-visibility: auto` on `.cue`). Still slow-ish:
`renderList()` rebuilds all cues (~95 ms) on split/merge/delete/replace-all. Re-measure after editor changes.

### SRT export (tested 2026-10-09)
Both exports (download + "Lagre SRT ved videoen" + export-all) go through `srt_bytes()`: identical bytes, UTF-8 without
BOM, CRLF. Saving writes `.srt.tmp` first, then keeps the old file as `.srt.bak` and replaces; export-all continues past
failures and returns `failed`. Verified: strict format check, the `srt` and `pysubs2` packages and ffmpeg (SRT → WebVTT)
all read a 683-cue export identically; timestamps carry correctly (59.9996 s → 00:01:00,000; > 1 h); empty cues skipped
with continuous numbering; Norwegian letters/typography, `<`, `&`, `-->` and stray blank lines are safe.
Open: "Flytt opp" (`pos: top`) is NOT in the SRT (no position in the format). `{n8}` would carry it in VLC/YouTube/
ffmpeg, but some players show it as literal text — ask the owner which player/site the SRTs go to before adding it.
Test hygiene: fake-mode export-all writes next to EVERY finished test video — only ever add copies under the scratch
folder as test videos (on 2026-10-09 test .srt files landed next to real files and had to be removed).

### Static files must never come from a stale cache (fixed 2026-10-09)
The app window keeps its HTTP cache between runs (pywebview `private_mode=False`); it reused old app.js /
editor.js after an update without even asking the server. Now `index()` adds `?v=<newest static mtime>` to
every /static/ link and a middleware sends `Cache-Control: no-cache` for /static/. Keep both.

### Queue order (2026-10-09)
`queue_key` in server.py: shortest *duration* first (not file size: transcription time follows length), unknown
length last by size. The worker picks with it and `state()` lists jobs in the same order (`list_order`: running,
queue, then finished in added order), so the first videos can be proofread while long ones run. Verified: the
editor (with video playing) does not pause the queue; nothing in the UI calls /api/queue except the Pause button.

### Measured but not done (2026-10-09)
- BatchedInferencePipeline (large, CPU, 6 threads): only ~10 % faster and 5 % of words differ → not worth it.
- Pickled nb dictionary: loads in 3.8 s instead of 10.1 s, but the file is 98 MB.
- h264_amf (AMD hardware encoder): 1.75x faster burn-in encode — dropped, burn-in is not used.

### Burn-in cleanup (fixed 2026-10-08)
`burn.burn` always removes its temp folder and `.part.mp4` (done, cancelled, error). Deleting a project stops
its transcription *and* burn-in first. Quit calls `burn.abort_all()` (kills ffmpeg; the burn-in resumes on the
next start). `Store.cleanup()` at startup removes project folders without meta.json and stale `burn\` folders.
Worker/Exporter use `safe_update` and catch `KeyError`, so a project deleted mid-job can't kill the thread
(before: one delete during burn-in broke all burn-ins until restart).

### Editor features (all exist and were tested in fake mode)
Review mode ("Gå gjennom": jumps only to flagged cues, Enter approves), find/replace, style panel for burn-in
(font, size, colour, box, position — preview overlay matches the burned result), export menu (SRT next to the
video, download SRT, burn-in video), undo/redo (also for split/merge/delete; toast with "Angre"), flags
(spelling, reading speed, line length, model disagreement with "Bruk", rescued speech, autofix with "Angre"),
"Hør på nytt" replays the cue (`playCue`, mousedown cancelled so the caret stays in the text). Ctrl+click a word in the text → `hearAt` plays that word ±0.5 s (matched to the model words in the cue by spelling, then by position; estimated from text position if the cue has no model words). Replaying the same cue within 12 s shows a toast nudge (once per cue) offering "Spill sakte (0,75×)"; by design a nudge, never automatic. The rate is restored on pause (`restoreRate`). Removed 2026-10-09: the model suggestion for one cue ("listen"/"Foreslå tekst", Alt+H, also used by "Ny undertekst her") — the human ear beats the model in the editor, and it let the editor run without the 1.5 GB model, glossary popup when a word is corrected to a similar spelling,
work timer (counts only active time), pause-on-type, waveform timeline (drag to scroll, wheel scrolls,
Ctrl+wheel zooms, drag cue edges to retime).
Keys outside text fields: Space play/pause, ←/→ ±5 s, ↑/↓ previous/next cue, Enter edit, Esc leave field, ? card.
Everywhere (Alt, never with Ctrl — Ctrl+Alt is AltGr on Norwegian keyboards): Alt+arrows, Alt+G review, Alt+R
replay, Alt+I/O start/end here (snaps to a word within 0.25 s), Alt+K approve, Alt+S split, Alt+M merge, Alt+W wrap,
Alt+Backspace delete, Alt+H suggest text (model), Alt+N new cue, Alt+−/Alt++ speed. Ctrl+F find, Ctrl+Z/Y undo/redo.
The list lives in i18n `keys_groups` (nb + en) and is shown as a small card under the timeline (keyboard button or
?), open the first time; tooltips name the key too. Hover tooltips only on non-obvious buttons (by design).

Added 2026-10-09 (all click-tested in fake mode, see git log):
- **Uncertain words**: model words with confidence < `UNSURE_P` (0.5) still present in the cue text → chip
  "Usikker: <words>"; clicking a word plays just that word and selects it. Counts as a review flag. Words come
  from `/api/projects/{pid}` (`words`: [start, end, p, text]). Threshold to be validated against real SRTs.
- **Snapping**: dragging a cue edge on the timeline snaps to word starts / word ends + 0.3 s (within ~10 px; hold
  Alt for free movement); small ticks at the bottom of the timeline mark word starts (zoom ≤ 40 s).
- **Fast structure edits**: split/merge/delete/insert use `spliceRows` (only changed rows + renumbering), ~70 ms
  incl. server wrap calls on 684 cues, instead of a full `renderList()`.
- **Progress + resume**: "312 av 683 godkjent · 28 merknader igjen" above the list; `POST /api/projects/{pid}/resume`
  stores {sel, t} in meta; the editor reopens there with a "Fra starten" toast.
- **Smooth timeline wheel**: `tlWheel` + `glideStep` ease the view (Ctrl+wheel zoom too), seek ≤ every 150 ms, land
  exactly at the end. Long words wrap inside chips (`overflow-wrap: anywhere`).
- Testing tip: the app window throttles timers and gets no keyboard input from CDP while it is in the background;
  run click/keyboard tests in a normal browser tab on the same port instead.

## Decisions already made (don't relitigate without reason)
- NB-Whisper large is the default model (best Norwegian accuracy); medium/small optional.
- No audio preprocessing (denoise etc.) — declined.
- `av<17` pinned (PyAV 17+ broke faster-whisper's `metadata_errors` arg).
- Windows only; zip + start.bat distribution; models download automatically.
- Python is fetched by uv into the app folder (`UV_PYTHON_PREFERENCE=only-managed`), never the system Python.
- UI is Norwegian-first, English toggle.
- **No virtual environment** (since 2026-10-08): packages go straight into uv's Python in
  `runtime\python\cpython-3.12*` (`uv pip install --python <it> --break-system-packages`). Reason: on the
  end user's company PC the venv launcher `.venv\Scripts\python.exe` was blocked ("Ingen tilgang", os error 5)
  while uv's own python.exe ran fine. `uv python install --no-bin --no-registry` so nothing is written outside
  the folder. start.bat, Teksting.vbs and dev\run_fake.bat find Python by globbing `cpython-3.12*`.
  `TEKSTING_NO_SHORTCUTS=1` makes start.bat skip the shortcuts (for testing a fresh install).
  Tested: fresh install from the zip into a folder with a space → app up in ~55 s; shortcut route works.
- Git: local repo + public GitHub remote `origin` (public since 2026-10-15) =
  https://github.com/JonasHicken/Teksteraskere-norsk (branch `main`). Commit after each verified
  change and push when a piece of work is done.

## Status: tested vs NOT tested
Tested (Linux, fake mode + Playwright headless): every UI flow, burn-in with real ffmpeg, learning, progress bar,
timeline drag, app-mode watchdog. Tested with real models (on Windows, earlier versions): transcription
quality, gap rescue, start.bat install.
**Verified on Windows 2026-10-08** (fake mode, via CDP on the real window): own window opens, video plays,
editor works, close-while-busy hides + auto-quit, second start re-shows, idle close quits, spell check.
**Not yet verified on Windows**: pinning from the real shortcut, DPI of the file picker, SRT download
Save dialog, new progress Tracker with real models (ETA accuracy), timeline drag.
Open (2026-10-08):
- Double-check flags varied between two app jobs on the *same* audio (4 vs 8 flags) although main-model words
  were identical. Not reproducible outside the server: small model is deterministic alone, after large, and
  through `Engine.transcribe` (also temperature fallback never triggered). Suspect something in the server job
  (hotwords/prompt? thread timing?). Flags are only review hints; subtitles come from the main model.
- i18n `offline` text still says "black window / start.bat", which no longer fits app mode.

## Open work (priority order)
1. **Verify the untested Windows items above**; read `data\teksting.log` for errors.
2. **Measure transcription accuracy** — waiting for 2–3 old videos + the end user's final SRTs. Use them
   as ground truth: word error rate of today's pipeline, then test accuracy-only changes (beam size up, VAD
   settings, hotwords/glossary) and keep only what measurably helps. Also check that SRT style (line breaks,
   timing) against ours.
3. **Vimeo** — unknown whether the end user uploads captions to Vimeo and whether we can get account access.
   Options: paste a Vimeo link to import the video; upload the finished track via Vimeo API. Ask first.
4. Collect real work-time numbers from 3–5 videos (Videoer page) and find where time goes.

## Conventions
- Keep it simple and functional; the owner likes the current clean look (light page, dark editor "studio",
  brand blue `#1f4f78`, subtitle yellow `#ffd84d`).
- New UI text → `i18n.js` in nb + en. Check Norwegian plurals ("1 sted" vs "2 steder").
- Long-running work goes through `Worker`/`Exporter`, never in a request handler.
- After changing UI, test in fake mode at 1440×900 and a narrow (~400 px) window, light and dark.
- Tests: `dev\test.bat` (pytest, 51 tests, ~5 s; fake transcription, temp data folder — see tests/conftest.py).
  Run them before every commit; add a test with every bug fix. No JS tests: the editor is verified in a
  headless browser per change.
- `style.css` has ONE rule per selector, grouped by screen (tokens, base, top bar, controls, pages, editor,
  overlays), with the media queries and reduced-motion block last. Edit the existing rule; never append an
  override at the end (that is how it grew to 640 lines of layered patches before 2026-10-09). Where order
  matters between equal-specificity rules there is a comment (`.keys-btn.on` after the transport rules,
  `.timeline .blk.sel` after `.active`, `.tools-row` after `.trow`, `.cue:hover` after `.cue.sel`).
- README.md (English, for developers) and `LES MEG.txt` (Norwegian, for users, goes in the zip) must be
  updated when features change.
- Never edit files in `data\` by hand while the app runs.
- Python scripts that rewrite files: `write_text(..., newline="
")` (Windows otherwise writes CRLF).
- Git: `.gitattributes` keeps `.bat/.vbs/.ps1/.txt` CRLF. Commit after each verified change.
