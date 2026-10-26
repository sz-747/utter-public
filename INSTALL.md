# Installing Utter (guide for coding agents)

You are installing Utter for the person you are working with. Follow these steps in order on their Windows PC, using PowerShell. Show them what you are doing, ask before anything that needs administrator rights, and finish with the checks in step 7. Stop and explain if a step fails; do not work around a failed download or check.

Utter is one repo: `dictation\` is the dictation client and `utter\` is the window. The speech server is a separate download (step 3).

## 0. Check the machine

- Windows 10 or 11, 64-bit.
- About 3 GB free disk space (1.5 GB download, then unpacked).
- Git, and Python 3.11 (`py -3.11 --version` or `python --version`). If Python 3.11 is missing, ask before installing it (e.g. `winget install Python.Python.3.11`).
- Microsoft Edge WebView2 Runtime (built into Windows 11; on Windows 10 install it if `utter.cmd` later fails to open a window).
- The Visual C++ runtime (`winget install Microsoft.VCRedist.2015+.x64`) if the speech server fails to start.

## 1. Choose a folder and clone

Use `%USERPROFILE%\Utter` unless the person names another folder.

```powershell
$base = "$env:USERPROFILE\Utter"
git clone https://github.com/sz-747/utter-public.git $base
Set-Location $base
```

## 2. Python environment

One environment serves both the window and the dictation client:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. Speech server and model

Skip this step on a machine that will use another PC's speech server over Tailscale (see "Remote dictation" in README.md).

The speech server is the packaged CapsWriter-Offline v2.6 release; the model is Qwen3-ASR 1.7B. Download both from the official releases:

- Server: `CapsWriter-Offline-20260914.zip` from <https://github.com/HaujetZhao/CapsWriter-Offline/releases/tag/v2.6>
- Model: `Qwen3-ASR-1.7B-q4_k.zip` (about 1.4 GB) from <https://github.com/HaujetZhao/CapsWriter-Offline/releases/tag/models>

Unpack them so these files exist (move contents up a level if a zip has its own top folder):

```
dictation\internal\runtime\start_server.exe
dictation\internal\runtime\config_server.py
dictation\internal\runtime\models\Qwen3-ASR\qwen3_asr_llm.gguf
dictation\internal\runtime\models\Qwen3-ASR\qwen3_asr_encoder_frontend.onnx
dictation\internal\runtime\models\Qwen3-ASR\qwen3_asr_encoder_backend.onnx
```

In `dictation\internal\runtime\config_server.py`, make sure `model_type = 'qwen_asr'` and `addr = '127.0.0.1'`.

## 4. Shortcuts

Create a Start menu and desktop shortcut called **Utter** that runs `"$base\.venv\Scripts\pythonw.exe" "$base\main.py"` with working directory `$base` and icon `$base\assets\utter.ico`. Utter's own Settings > System > "Launch Utter at login" adds the login shortcut; leave that to the person.

## 5. First start

Run `$base\utter.cmd`. Utter starts the speech server (up to a minute the first time while the model loads) and the dictation client in the background, then shows its window.

## 6. Optional: AI polish

Filler words such as "um" and "uh" are removed without any AI model. For smarter cleanup (self-corrections, "like", "you know"), AI polish needs a local model server. If the person already uses LM Studio or Ollama, point `dictation\LLM\default.py` at it (LM Studio: `provider = 'openai'`, `api_url = 'http://127.0.0.1:1234/v1'` (use 127.0.0.1, not localhost: on Windows, localhost adds about 2 seconds to every request), the model id from `lms ls`, and `extra_options = {'extra_body': {'reasoning_effort': 'none'}}` for models that think before answering). Do not download a model without asking; they are several GB.

## 7. Checks

Report each as passed or failed:

1. `Get-NetTCPConnection -LocalPort 6016 -State Listen` returns a listener (speech server running; skip on a remote-dictation machine).
2. `$base\dictation\appdata\status.json` exists and was updated in the last 10 seconds (dictation client running).
3. The three test suites in README.md > Test pass, run from `$base`.
4. The Utter window opens and its banner says **Utter is ready** with a microphone listed.
5. Ask the person to press Right Ctrl, say a sentence in Notepad, and press Right Ctrl again. The sentence should be typed.
