@echo off
title ComfyUI Restart v4

echo ============================================
echo   ComfyUI Strong Restart v4
echo ============================================

echo.
echo [1/3] Killing old ComfyUI process (by exe path)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.MainModule.FileName -eq 'D:\ComfyUI-WorkFisher-V2\python\python.exe' } | Stop-Process -Force"
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
if not exist "D:\ComfyUI-WorkFisher-V2\python\python.exe" (
  echo   ERROR: python.exe not found.
  pause
  exit /b 1
)
cd /d "D:\ComfyUI-WorkFisher-V2\ComfyUI"
start "ComfyUI" "D:\ComfyUI-WorkFisher-V2\python\python.exe" "D:\ComfyUI-WorkFisher-V2\ComfyUI\main.py" --lowvram --async-offload 2 --port 8188 --listen 127.0.0.1
echo   Launched.

echo.
echo ============================================
echo   Done. Wait 2-3 min for LTX 22B to load.
echo   gen_ltx will auto-resume when 8188 comes back.
echo ============================================
pause