@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto launch_error

:: Clear PYTHONPATH to avoid conflicts with global Python environments.
set PYTHONPATH=

:: Point Ollama to the existing model store
set OLLAMA_MODELS=%USERPROFILE%\.ollama\models

if not defined DISTILLER_DEFAULT_PROJECT (
  set "DISTILLER_DEFAULT_PROJECT=%~dp0..\\video-account-distiller-projects\\workspace"
)

if exist "%~dp0dist\windows\VideoAccountDistiller\VideoAccountDistiller.exe" (
  start "" "%~dp0dist\windows\VideoAccountDistiller\VideoAccountDistiller.exe"
  exit /b 0
)

where uv >nul 2>&1
if errorlevel 1 (
  echo ERROR: uv was not found.
  echo Install uv from https://docs.astral.sh/uv/ and try again.
  goto launch_error
)

echo Preparing the native Windows desktop application...
uv sync --extra desktop
if errorlevel 1 goto launch_error

echo Starting Video Account Distiller Desktop...
echo.

uv run distiller-desktop
if errorlevel 1 goto launch_error

echo.
echo Video Account Distiller Desktop has stopped.
pause
exit /b 0

:launch_error
echo.
echo The application could not start. This window will stay open.
echo Copy the error shown above if you need help.
pause
exit /b 1
