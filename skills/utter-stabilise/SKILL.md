---
name: utter-stabilise
description: Utter project only. Diagnose why Utter dictation loses words, types nothing, skips AI polish or is slow - Bluetooth headset mic dropouts, the settling period after a headset connects, a mic that sends silence, a client bug, a broken speech server or polish model, or a GPU filled by other programs - from the dictation client's logs and capture reports, the Windows audio event log, a short live mic test and a synthetic end-to-end check. Use when the user says Utter dictation is "unstable", "cutting out", "not typing anything", "the text doesn't show up", "AI polish isn't working", "slow" or "laggy", or asks why Bluetooth (e.g. AirPods) dictation fails.
---

# Utter stabilise

## Metadata

- **Type**: Workflow
- **Applicable scenarios**: Utter dictation on Windows drops words, types nothing, types unpolished text, is slow to appear, or is "unstable". Not for other apps' audio, Utter UI bugs, or speech-recognition accuracy (wrong words from full audio; use the dictionary).
- **Output location**: a chat reply; nothing is written to disk.
- **Created**: 2026-10-26
- **Updated**: 2026-10-26

## Goal and boundaries

Name the cause of recent Utter dictation failures with evidence from the user's machine, say what fixes it, and confirm the fix with a live test.

Scope: this repo and its dictation client (`dictation/`). The skill reads the client's own log, capture and archive formats, so it does not apply to other dictation apps or other projects.

Out of scope: changing Utter or client code, changing Windows audio or Bluetooth settings, pairing or unpairing devices, and restarting the dictation client. Recommend these; do them only when the user asks. The user does the physical steps (case reset, moving closer, disconnecting a phone).

## Acceptance criteria

- **Complete**: the reply names the outcome class for the failures the user means, with their timestamps and held/delivered seconds or wav peak; states the minutes since the last mic connect when settling is plausible; gives the fix for that class; and reports a `live` result taken after the fix.
- **Partial**: as above, but each missing piece is named: event log unreadable (no settle-time evidence), live test not run (user declined, or `live` exit 3 with its BLOCKED reason), or failures that predate the capture folder (`empty_result`, cause not attributable).
- **Blocked**: `report` exits 2 (client folder or its logs not found). Say which path was missing; classify nothing.
- No class, timestamp or number appears in the reply unless `report` or `live` printed it.

## Resources and constraints

- The client folder is `dictation/` in this repo. Inside it: `logs/client_YYYYMMDD.log` (one file per client start; it keeps logging past midnight), `appdata/captures/<start>.json|.wav` (the last ~40 recordings: held vs delivered seconds, gaps, verdict, audio), `transcripts/transcripts.sqlite3` (every dictation's text).
- [scripts/mic_diag.py](scripts/mic_diag.py), run from the repo root with the repo's `.venv`:
  - `.venv\Scripts\python.exe skills\utter-stabilise\scripts\mic_diag.py report [--days 3] [--device AirPods] [--client <folder>]`: read-only, offline. Classifies every recording, lists the latest failures, and builds a settle-time table (failure rate by minutes since the mic last connected, from Windows `Microsoft-Windows-Audio/Operational` event 65 via `wevtutil`).
  - `.venv\Scripts\python.exe skills\utter-stabilise\scripts\mic_diag.py live [--device AirPods] [--seconds 6]`: opens the mic for 6 s through MME (like the client) and reports seconds delivered, gaps and peak level. It records nothing to disk.
  - `--device` is a substring of the Windows mic endpoint name; without it, `report` looks at every mic and `live` uses the first one. Exit codes: 0 done; 2 client folder not found; 3 live test blocked (no sounddevice, no matching device, mic would not open). BLOCKED messages keep the underlying error and list the available inputs.
- [scripts/pipeline_check.py](scripts/pipeline_check.py) `doctor [--client <folder>]`, run from the repo root with the repo's `.venv`: sends [assets/doctor-check.wav](assets/doctor-check.wav) (Windows TTS reading "This is the Utter doctor check. Um, the quick brown fox jumps over the lazy dog."; no user data) to the speech server as a dictation and times it, reports the local resources the speech server and polish model share (GPU memory from `nvidia-smi`, the models Ollama holds and which are kept forever), then sends the text through the client's own AI polish path and output guard. Prints one PASS/FAIL/SKIP line per stage and a `Result:` class. It types and saves nothing, and checks polish even when it is off in Settings (it says so). Exit 0 all passed, 1 a stage failed, 2 client folder not found. Takes seconds; run it first for any "nothing works", polish or "slow" complaint, and after every fix.
- `pipeline_check.py homophones [--client <folder>]`: checks sound-alikes both ways. It rechecks saved mishearings with today's dictionary, says dictionary words with Windows TTS, then says ordinary sound-alikes that should stay unchanged. It closes the archive before transcribing, and does not type, save or learn. Exit 3 means the speech server is down.
- `live` uses the user's microphone: run it only after the user agrees or asks for a check, and not while they are dictating.
- Tests: `.venv\Scripts\python.exe -B -m unittest discover -s skills/utter-stabilise/tests -v` from the repo root (offline fixtures, separate from Utter's `tests/` suite).

## Outcome classes and what to tell the user

| Class | Evidence | Meaning and fix |
|---|---|---|
| `partial_audio` | log `Audio lost` with "device/Bluetooth"; delivered far below held; gaps of 0.3-2 s | The Bluetooth link is starved. Within ~10 min of a connect, wait (see settling). Otherwise: case reset (both earbuds in the case for 10 s), move closer to the PC with nothing in between, try one earbud, check the battery, pause heavy Wi-Fi traffic (many PCs share one antenna between Wi-Fi and Bluetooth). Fallback: a wired or USB mic. |
| `no_audio` | delivered 0.0 s or `Skipping empty recording task`; report shows "mic endpoint was unplugged" | The headset was not connected (in the case, taken by a phone, asleep). Nothing typed and no message. Reconnect. |
| `silent_mic` | capture verdict `ok`, full length, but wav peak under 0.02 | The mic streamed silence, so no text and no message. Seen as the first dictation after a long idle. Dictate again; if it repeats, reconnect the headset. |
| `client_bug` | verdict "audio arrived but did not reach recognition (client bug)" | A dictation client problem, not the mic. The full audio is in the capture; attach it to a bug report. |
| `empty_result` | empty final result with no capture to inspect | Unknown: very short or quiet speech, or a failure before captures existed. Not attributable without audio. |

`doctor` results:

| Result | Meaning and fix |
|---|---|
| `server_down` | Nothing answers at the speech server's address. Start dictation in Utter; on a remote-dictation laptop, check Tailscale reaches the PC. |
| `recognition_wrong` | The server answers but mishears clean TTS by more than 25%: wrong model or a broken server. Check the client log. |
| `recognition_slow` | The 6.4 s sample took over 2 s to recognise (about 0.3 s on a desktop GPU), so every dictation waits. Read the `local resources` line next: a nearly full GPU is the usual cause. |
| `resources_full` | GPU memory is 90% or more in use. The speech server and polish model share the GPU, so recognition slows down and the polish model can be pushed out (the next polish then waits to reload it). The line lists Ollama's models; ones `(kept forever)` belong to other jobs (keep_alive -1) and stay after the job ends: `ollama stop <model>` once that job is done, after asking whether it still needs them. Otherwise close other GPU programs (games, emulators). |
| `polish_unreachable` | The polish server in `dictation/LLM/default.py` isn't listening. Ollama: `ollama serve` (the client also starts it on the next long dictation). Dictation still types, unpolished. |
| `polish_model_missing` | Ollama runs but lacks the model named in `LLM/default.py`: `ollama list`, then fix the name or pull the model (ask first; models are GBs). |
| `polish_empty` / `polish_error` | The model returned nothing or the request failed, so the client typed the raw text. Empty from a thinking model means `think` wasn't sent as false. |
| `polish_rejected` | The output guard refused the reply (rewrote, answered or grew the text); the stage line gives the guard's reason. Look at the prompt and model. |
| `polish_slow` | Polish took over 8 s. A first call after the model unloaded includes loading it: run `doctor` again; still slow means the model is too big or the GPU is busy. |

## Settling after a connect

One machine, October 2026, AirPods Pro, 19 mic connects and 251 recordings: 47% of recordings in the first 2 minutes after a connect lost audio, 10-14% at 2-10 minutes, and 0 of 136 between 10 and 60 minutes. About half the connects were clean from the first minute. Reconnecting restarts the clock, so repeated case resets during a bad patch can prolong it. Quote the current machine's table from `report`, not these numbers.

## Method suggestions

- Match the complaint: words lost or nothing typed -> `report` (then `live`); unpolished text, nothing at all, or dictation slow to appear -> `doctor`.
- `report` answers most questions without touching the mic; `live` judges the link now. HEALTHY means at least 95% of the time delivered and no gap over 0.2 s, so it is a good check after each fix the user tries.
- When several classes appear, lead with the one covering the failures the user means (match by time).

## Known pitfalls

- **Blaming another device.** A phone paired to the PC looked like the cause of AirPods dropouts; disconnecting it changed nothing, and the link recovered with time. Check minutes since the last connect first, and retest with `live` after each change.
- **Trusting the capture verdict.** A recording marked `ok` was full-length silence (peak 0.007) and typed nothing. The verdict only checks for missing audio; `report` adds the wav-peak check (`silent_mic`).
- **Reading a quiet event log as broken.** Event 65 is logged only on change; no newer event meant the headset had not reconnected, not that logging had stopped.
- **"Is it the network?" when dictation lags.** With the speech server on the same PC, lag is local. The client log's `delay: N s` on each `Final result:` line rose from a median 0.4 s to 4.7-7.9 s after another program loaded two Ollama models with keep_alive forever and filled the GPU; once they were gone it was back under 1 s. Run `doctor` (recognition speed, local resources) and compare those delays over time before blaming the network or the model.
- **Polish that answers but returns nothing.** The polish server answered and Utter showed it reachable, but Qwen 3.5 on Ollama thought for 11 s and returned empty text because `think` was left unset. Reachability is not a working polish; `doctor` runs a real request (`polish_empty`).
- **Changing the client's log wording.** `report` finds recordings by the client's log lines (`Pressed: recording started`, `Audio lost: held ...`, `Final result: ...`). The tests check those lines still exist in the client's code; update `mic_diag.py` with them.

## Output

A short chat reply in this shape:

```
Cause: the Bluetooth link was starved right after the AirPods connected (partial_audio).
Evidence: 23:30-23:40, 9 recordings sent 0.1-4.7 s of 2-15 s held; the first came 1.1 min after the mic connected at 23:29. On this PC, 0 of 136 recordings 10-60 min after a connect lost audio.
What to do: wait about 10 minutes without reconnecting; if it persists, case reset and move closer to the PC.
Live test after the fix: 5.95 s of 6 s, no gaps (HEALTHY).
```
