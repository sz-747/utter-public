# Evaluating Utter voice workflows

This is Utter's adaptation of [How to Evaluate Voice Agents](https://x.com/manthanguptaa/status/2088604116771815710) by @manthanguptaa. The article is a reference, not evidence that Utter has passed these checks. Its cited studies and suggested numeric thresholds have not been independently verified here. The article text is not redistributed in this repository.

## What a successful operation means

For dictation, follow one operation from microphone capture through speech recognition, optional AI polish, and the actual text in the intended application. The bundled `dictation/` client owns capture, recognition, polish and typing. The `utter/` window shows status and settings.

For the Notetaker, follow microphone and speaker capture through segmented recognition, saved transcript, and saved summary. `utter/meeting.py` owns recording and transcription, `utter/notes.py` persists text, and `utter/summary.py` generates notes. Meeting audio is not saved.

| Check | Evidence needed |
| --- | --- |
| Completeness and accuracy | Compare recognised text with a human checked English reference, including names, numbers, negation, beginnings and endings. Report word error rate and critical-field errors separately. |
| Faithful polish | Compare reference meaning, recognition text and polished text. Check whether numbers, negation, uncertainty or decisions changed. |
| Time to usable result | Measure from end of speech to text visible in the target field, and from end of meeting to persisted transcript and summary. Report typical and slower cases with sample sizes. |
| Delivery | Inspect the target field or saved database state. A successful recognition response alone does not establish delivery. |
| Summary support | Check decisions, owners, dates and unresolved points against transcript passages. A valid summary format does not prove factual support. |
| Reliability | Repeat the same conditions, record successes over attempts, and keep regression cases from real failures. |

## First baseline

Start with roughly 10 to 15 English scenarios covering names, self corrections, negation, dates, short and long speech, long pauses, a newly connected microphone, muted input, an unavailable speech server, AI timeout, overlapping meeting speakers, and stopping with a transcription segment still queued. Save the expected and observed outcome, conditions and version for each. Keep some cases aside from tuning.

Fixed audio can check recognition consistency. It cannot prove live microphone capture or typing into another app. Check those on the real path. Serious failures such as reversed negation, invented meeting decisions, text in the wrong window or a lost meeting tail need separate investigation; an average score cannot hide them. Choose latency limits after measuring a baseline.

Utter's existing Notetaker policy keeps meeting audio out of storage. Use consented test material or synthetic audio for replayable checks. If a production recording was not retained, mark its audio as unavailable; a later re-recording is a new test. This document proposes evaluation work and reports no new performance measurement or live verification.
