@echo off
setlocal
set "APP_DIR=%~dp0"
set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%CODEX_PY%" (
  "%CODEX_PY%" "%APP_DIR%wakppu_click_widget.py"
  exit /b %ERRORLEVEL%
)

py -3 "%APP_DIR%wakppu_click_widget.py"
if not errorlevel 9009 exit /b %ERRORLEVEL%

python "%APP_DIR%wakppu_click_widget.py"
exit /b %ERRORLEVEL%
