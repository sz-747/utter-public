# Improvement activity in the public build

Home has a read-only card for daily improvement receipts under `dictation/appdata/learning/`. The bundled client owns the receipt format in `dictation/util/learning_status.py`; `utter/improvements.py` presents its bounded view. The card shows the last finding, action, verification limit and up to eight history entries. Raw evidence files, commands and error stacks are not returned to the page; the review's bounded finding text is displayed. A completed review or passing tests are not presented as proof of better everyday use.

No automatic daily review is configured in this public build, and no real-use outcome is claimed. If a compatible review writes a receipt, Home can show it. A missing written report after a completed review is marked pending, rather than failing the review itself. A genuine failed run remains visible. The Settings and Notetaker flows are unchanged by this reader.

The present evidence is offline unit tests of the receipt shapes, Home API and call detection. A browser or native WebView2 check, real microphone capture, target-field delivery and user-outcome measurement remain pending. The Notetaker capture and summary path is not yet instrumented as a daily review source. See [voice evaluation](voice-evaluation-reference.md) for proposed checks.
