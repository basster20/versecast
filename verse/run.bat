@echo off
rem Launch Verse in its own application window.
rem Falls back to a browser tab only if the window host is unavailable.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" app.py %*
  goto :eof
)

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopython

rem NDI is checked separately: its runtime is a system install, so a missing one
rem must not send this script into a reinstall loop on every launch.
%PY% -c "import webview, psutil, vosk, sounddevice" >nul 2>nul
if errorlevel 1 (
  echo Installing Verse's components once ^(window, memory watch, speech^)...
  %PY% -m pip install --quiet -r requirements.txt
)

rem Offline detection is checked on its own: it is optional, and a machine
rem without onnxruntime must still open the app rather than reinstall forever.
%PY% -c "import onnxruntime, tokenizers" >nul 2>nul
if errorlevel 1 (
  echo Installing the offline detection components once ^(ONNX Runtime^)...
  %PY% -m pip install --quiet "onnxruntime>=1.20" "tokenizers>=0.21"
)

%PY% -c "import webview" >nul 2>nul
if errorlevel 1 goto :browser

start "" %PY%w app.py %*
goto :eof

:browser
%PY% serve.py %*
goto :eof

:nopython
echo Python 3 was not found. Install it from https://python.org and run this again.
pause
