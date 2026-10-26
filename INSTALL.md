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

Skip this step on a machine that will use another PC's speech server over Tailscale (see [Remote dictation over Tailscale](#remote-dictation-over-tailscale)).

The speech server is the packaged CapsWriter-Offline v2.6 release (`CapsWriter-Offline-20260914.zip`, about 110 MB, from <https://github.com/HaujetZhao/CapsWriter-Offline/releases/tag/v2.6>); the model is Qwen3-ASR 1.7B (`Qwen3-ASR-1.7B-q4_k.zip`, about 1.4 GB, from <https://github.com/HaujetZhao/CapsWriter-Offline/releases/tag/models>). Download and unpack both with these commands; no browser is needed. The server zip has everything inside a `CapsWriter-Offline` folder, and the model zip holds just the three model files.

```powershell
$runtime = "$base\dictation\internal\runtime"
$download = "$env:TEMP\utter-setup"
New-Item -ItemType Directory -Force $download, $runtime | Out-Null
curl.exe -L --fail -o "$download\server.zip" https://github.com/HaujetZhao/CapsWriter-Offline/releases/download/v2.6/CapsWriter-Offline-20260914.zip
curl.exe -L --fail -o "$download\model.zip" https://github.com/HaujetZhao/CapsWriter-Offline/releases/download/models/Qwen3-ASR-1.7B-q4_k.zip
Expand-Archive "$download\server.zip" $download -Force
Copy-Item "$download\CapsWriter-Offline\*" $runtime -Recurse -Force
Expand-Archive "$download\model.zip" "$runtime\models\Qwen3-ASR" -Force
# Serve on this PC only, with the Qwen3-ASR model
$cfg = "$runtime\config_server.py"
(Get-Content $cfg -Raw -Encoding utf8) -replace "(?m)^(\s*addr\s*=\s*)'[^']*'", "`$1'127.0.0.1'" -replace "(?m)^(\s*model_type\s*=\s*)'[^']*'", "`$1'qwen_asr'" | Set-Content $cfg -Encoding utf8
Remove-Item $download -Recurse -Force
```

Then check that these files exist:

```
dictation\internal\runtime\start_server.exe
dictation\internal\runtime\config_server.py
dictation\internal\runtime\models\Qwen3-ASR\qwen3_asr_llm.gguf
dictation\internal\runtime\models\Qwen3-ASR\qwen3_asr_encoder_frontend.onnx
dictation\internal\runtime\models\Qwen3-ASR\qwen3_asr_encoder_backend.onnx
```

and that `dictation\internal\runtime\config_server.py` has `model_type = 'qwen_asr'` and `addr = '127.0.0.1'`.

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
3. The three test suites in [Test](#test) pass, run from `$base`.
4. The Utter window opens and its banner says **Utter is ready** with a microphone listed.
5. Ask the person to press Right Ctrl, say a sentence in Notepad, and press Right Ctrl again. The sentence should be typed.

---

The sections below are reference for later changes. Use them when the person asks.

## Run

```powershell
utter.cmd
```

Opening Utter starts dictation if it is off (Settings > System can turn that off). Closing the window leaves dictation running. Press Right Ctrl (or mouse button X2), speak, and press it again.

To run dictation without the window: `dictation\start-dictation.cmd`, and `dictation\stop-dictation.cmd` to stop it.

## Configure

- **Settings in the window**: shortcuts, microphone, sounds, muting other apps, learning, AI review, AI polish and output.
- **The dictionary**: `dictation\hot.txt` (words), `dictation\hot-rule.txt` (replacement rules) and `dictation\hot-rectify.txt` (examples for AI polish). They are created from the `*.example.txt` files the first time the client runs, and Git ignores them. Words can also be edited in the window's Dictionary.
- **Everything else**: `dictation\config_client.py` (defaults) and `dictation\LLM\default.py` (the AI polish model and prompt). Step 6 covers pointing AI polish at LM Studio or Ollama (`provider = 'ollama'`); after that, switch it on in Settings > Dictation.

## Remote dictation over Tailscale

A weaker machine can use another PC's speech server:

1. On the PC with the speech server, keep the server on `127.0.0.1` and share the port on the tailnet: `tailscale serve --bg --tcp 6016 tcp://127.0.0.1:6016`.
2. On the laptop, install Utter but skip step 3. In `dictation\config_client.py`, set `addr` to the PC's Tailscale name (for example `'desktop.your-tailnet.ts.net'`).

With no local server installed, Utter starts only the client, and the banner names the PC it is using.

## MCP for coding agents

Add a server named `utter` to each agent's MCP config that runs, from the Utter folder:

```
.venv\Scripts\python.exe -m utter.mcp_server
```

Set `UTTER_MCP_CLIENT` (for example `codex` or `claude`) in that entry's environment so Utter shows each agent's last use. LM Studio can be added from Settings > MCP.

## Test

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t .
cd dictation; ..\.venv\Scripts\python.exe -m unittest discover -s util -p "test_*.py" -t .; cd ..
.venv\Scripts\python.exe -B -m unittest discover -s skills/utter-stabilise/tests
```

The tests run offline and need no speech server. Two of them touch Windows itself and clean up after themselves: one copies text to the clipboard and puts the previous clipboard back, and one stores and deletes a test entry (`Utter/unit-test-secret`) in Windows Credential Manager.
