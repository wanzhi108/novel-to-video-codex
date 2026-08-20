@echo off
title ComfyUI Restart v4

echo ============================================
echo   ComfyUI Strong Restart v4
echo ============================================

echo.
echo [1/3] Killing old ComfyUI process...
if not defined COMFYUI_PATH set "COMFYUI_PATH=%~dp0..\ComfyUI"
if not defined COMFYUI_PYTHON (
  if exist "%COMFYUI_PATH%\..\python\python.exe" (
    set "COMFYUI_PYTHON=%COMFYUI_PATH%\..\python\python.exe"
  ) else (
    set "COMFYUI_PYTHON=python"
  )
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$py = $env:COMFYUI_PYTHON; Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object { ($py -and $_.ExecutablePath -eq $py) -or ($_.CommandLine -match 'ComfyUI[\\/]main\.py') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo   Done.

echo.
echo [2/3] Waiting up to 60s for port 8188 to free...
set PORT_FREE=0
for /L %%i in (1,1,30) do (
  netstat -ano | findstr ":8188.*LISTENING" >nul
  if errorlevel 1 (
    set PORT_FREE=1
    goto :portok
  )
  echo   waiting... %%i/30
  timeout /t 2 /nobreak >nul
)
:portok
if %PORT_FREE%==1 (echo   Port 8188 is free.) else (echo   WARNING: port still occupied, try anyway.)

echo.
echo [3/3] Starting new ComfyUI...
if not exist "%COMFYUI_PATH%\main.py" (
  echo   ERROR: ComfyUI main.py not found at "%COMFYUI_PATH%".
  echo   Set COMFYUI_PATH to the ComfyUI install directory.
  pause
  exit /b 1
)
cd /d "%COMFYUI_PATH%"
start "ComfyUI" "%COMFYUI_PYTHON%" "%COMFYUI_PATH%\main.py" --lowvram --async-offload 2 --port 8188 --listen 127.0.0.1
echo   Launched.

echo.
echo ============================================
echo   Done. Wait 2-3 min for LTX 22B to load.
echo   gen_ltx will auto-resume when 8188 comes back.
echo ============================================
pause