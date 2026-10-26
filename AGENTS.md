# Utter project instructions

Utter is a pywebview (WebView2) desktop window (`utter/`) over the dictation client in `dictation/` (a fork of CapsWriter-Offline).

- Dictation behavior belongs in `dictation/`. The window only reads the client's files and writes `appdata/settings.json` and the dictionary (hot) files. Its own data is the Notetaker store (`utter/notes.py`, `%APPDATA%\Utter\notetaker.sqlite3`); notetaker preferences live there, not in the client's settings.
- Notetaker AI runs only on the local AI polish model or the Codex app server (`utter/summary.py`); add no other AI backend.
- File formats are owned by the client's modules (`config_client`, `util.app_settings`, `util.dictionary_files`, `util.text_metrics`, `util.client.diary.archive`). Import them through `utter.dictation`; never copy them into `utter/`. When the window starts reading another client file or field, add it to `tests/test_client_formats.py`.
- English only (DS-011): no language-specific processing for other languages.
- UI is plain HTML/CSS/JS in `utter/web` with no build step. Python methods the page calls live in `utter/api.py` and return JSON data or `{'error': ...}`.
- One Python environment, `.venv` at the repo root, serves the window and the client.
- Before committing, run all three test suites (see INSTALL.md > Test).
- Product choices already made are in `docs/decision-surfaces.md`.
