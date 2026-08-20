@echo off
set PYTHONPATH=
set WANDB_DISABLED=true
set WANDB_MODE=disabled
REM COMFYUI_PATH / COMFYUI_PYTHON 可用环境变量覆盖默认搜索路径
if not defined COMFYUI_PATH set "COMFYUI_PATH=%~dp0..\ComfyUI"
if not defined COMFYUI_PYTHON (
  if exist "%COMFYUI_PATH%\..\python\python.exe" (
    set "COMFYUI_PYTHON=%COMFYUI_PATH%\..\python\python.exe"
  ) else (
    set "COMFYUI_PYTHON=python"
  )
)
cd /d "%COMFYUI_PATH%"
"%COMFYUI_PYTHON%" -s main.py --lowvram --async-offload 2 --port 8188 --listen 127.0.0.1
