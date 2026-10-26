@echo off
rem Opens the Utter window. It starts dictation too unless that is turned off in Settings.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
