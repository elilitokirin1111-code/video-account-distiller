@echo off
setlocal
cd /d "%~dp0"

:: Clear PYTHONPATH to avoid conflicts with Hermes global venv
set PYTHONPATH=

:: Point Ollama to the existing model store
set OLLAMA_MODELS=%USERPROFILE%\.ollama\models

uv run distiller %*
if errorlevel 1 exit /b %errorlevel%
