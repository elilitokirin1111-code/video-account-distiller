@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not defined DISTILLER_DEFAULT_PROJECT (
  set "DISTILLER_DEFAULT_PROJECT=%~dp0..\video-account-distiller-projects\workspace"
)

where uv >nul 2>&1
if errorlevel 1 (
  echo 未找到 uv。请先安装 uv：https://docs.astral.sh/uv/
  pause
  exit /b 1
)

echo 正在启动 Video Account Distiller...
echo 浏览器会在服务就绪后自动打开。
echo 关闭此窗口即可停止应用。
uv run distiller-web

if errorlevel 1 (
  echo.
  echo 应用启动失败，请保留此窗口中的错误信息。
  pause
)
