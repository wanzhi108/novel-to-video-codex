@echo off
set PYTHONPATH=
set WANDB_DISABLED=true
set WANDB_MODE=disabled
cd /d "D:\ComfyUI-WorkFisher-V2\ComfyUI"
D:\ComfyUI-WorkFisher-V2\python\python.exe -s main.py --lowvram --async-offload 2 --port 8188 --listen 127.0.0.1
