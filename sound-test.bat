@echo off
setlocal
set "APP_DIR=%~dp0"
set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%CODEX_PY%" (
  "%CODEX_PY%" "%APP_DIR%wakppu_widget.py" --sound-test
  pause
  exit /b %ERRORLEVEL%
)

py -3 "%APP_DIR%wakppu_widget.py" --sound-test
pause
