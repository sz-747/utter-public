---
name: utter-stabilise
description: Utter project only. Diagnose why Utter dictation loses words or types nothing - Bluetooth headset mic dropouts, the settling period after a headset connects, a mic that sends silence, or a client bug - from the dictation client's logs and capture reports, the Windows audio event log and a short live mic test. Use when the user says Utter dictation is "unstable", "cutting out", "not typing anything", "the text doesn't show up", or asks why Bluetooth (e.g. AirPods) dictation fails.
---

# Utter stabilise

## Metadata

- **Type**: Workflow
- **Applicable scenarios**: Utter dictation on Windows drops words, types nothing, or is "unstable". Not for other apps' audio, Utter UI bugs, or speech-recognition accuracy (wrong words from full audio; use the dictionary).
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

## Settling after a connect

One machine, October 2026, AirPods Pro, 19 mic connects and 251 recordings: 47% of recordings in the first 2 minutes after a connect lost audio, 10-14% at 2-10 minutes, and 0 of 136 between 10 and 60 minutes. About half the connects were clean from the first minute. Reconnecting restarts the clock, so repeated case resets during a bad patch can prolong it. Quote the current machine's table from `report`, not these numbers.

## Method suggestions

- `report` answers most questions without touching the mic; `live` judges the link now. HEALTHY means at least 95% of the time delivered and no gap over 0.2 s, so it is a good check after each fix the user tries.
- When several classes appear, lead with the one covering the failures the user means (match by time).

## Known pitfalls

- **Blaming another device.** A phone paired to the PC looked like the cause of AirPods dropouts; disconnecting it changed nothing, and the link recovered with time. Check minutes since the last connect first, and retest with `live` after each change.
- **Trusting the capture verdict.** A recording marked `ok` was full-length silence (peak 0.007) and typed nothing. The verdict only checks for missing audio; `report` adds the wav-peak check (`silent_mic`).
- **Reading a quiet event log as broken.** Event 65 is logged only on change; no newer event meant the headset had not reconnected, not that logging had stopped.
- **Changing the client's log wording.** `report` finds recordings by the client's log lines (`Pressed: recording started`, `Audio lost: held ...`, `Final result: ...`). The tests check those lines still exist in the client's code; update `mic_diag.py` with them.

## Output

A short chat reply in this shape:

```
Cause: the Bluetooth link was starved right after the AirPods connected (partial_audio).
Evidence: 23:30-23:40, 9 recordings sent 0.1-4.7 s of 2-15 s held; the first came 1.1 min after the mic connected at 23:29. On this PC, 0 of 136 recordings 10-60 min after a connect lost audio.
What to do: wait about 10 minutes without reconnecting; if it persists, case reset and move closer to the PC.
Live test after the fix: 5.95 s of 6 s, no gaps (HEALTHY).
```
