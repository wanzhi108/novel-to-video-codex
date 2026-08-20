@echo off
chcp 65001 >nul
title Novel2Vid V7.1 Launcher
setlocal EnableDelayedExpansion

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║        Novel2Vid V7.1 — 小说转竖屏短视频 AI 生成器        ║
echo ║  IP-Adapter 角色锚定 · Ken Burns · CosyVoice2 · 双帧LTX ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM ============================================================
REM 1. 检查 Python (优先使用项目 venv)
REM ============================================================
echo [1/6] 检查 Python...
set PYTHON_CMD=python
if exist "venv\Scripts\python.exe" (
    set PYTHON_CMD=venv\Scripts\python.exe
    echo   [✓] 使用项目 venv Python
) else (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo   [✗] 未找到 Python，请先安装 Python 3.11+
        pause
        exit /b 1
    )
)
for /f "tokens=2" %%v in ('%PYTHON_CMD% --version 2^>^&1') do set PYVER=%%v
echo   [✓] Python %PYVER%

REM ============================================================
REM 2. 检查依赖
REM ============================================================
echo.
echo [2/6] 检查依赖...
if "%PYTHON_CMD%"=="venv\Scripts\python.exe" (
    %PYTHON_CMD% -c "import fastapi" >nul 2>&1
    if errorlevel 1 (
        echo   [!] venv 依赖未安装，正在安装...
        %PYTHON_CMD% -m pip install -r requirements.txt
    ) else (
        echo   [✓] 依赖已安装
    )
) else (
    pip show fastapi >nul 2>&1
    if errorlevel 1 (
        echo   [!] 依赖未安装，正在安装...
        pip install -r requirements.txt
    ) else (
        echo   [✓] 依赖已安装
    )
)

REM ============================================================
REM 3. 检查 ComfyUI
REM ============================================================
echo.
echo [3/6] 检查 ComfyUI (127.0.0.1:8188)...
curl -s --connect-timeout 3 http://127.0.0.1:8188/system_stats >nul 2>&1
if errorlevel 1 (
    echo   [!] ComfyUI 未启动 — 图片/视频功能不可用
) else (
    echo   [✓] ComfyUI 已连接
)

REM ============================================================
REM 4. 检查 CosyVoice 2
REM ============================================================
echo.
echo [4/6] 检查 CosyVoice 2 (localhost:50000)...
curl -s --connect-timeout 3 http://localhost:50000/ >nul 2>&1
if errorlevel 1 (
    echo   [!] CosyVoice 2 未启动 — 使用 Edge-TTS 回退
) else (
    echo   [✓] CosyVoice 2 已连接 (电影级配音)
)

REM ============================================================
REM 5. 检查 FFmpeg
REM ============================================================
echo.
echo [5/6] 检查 FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo   [!] FFmpeg 未安装 — 后期合成不可用
) else (
    echo   [✓] FFmpeg 已安装
)

REM ============================================================
REM 6. 检查 DeepSeek API Key
REM ============================================================
echo.
echo [6/6] 检查 DeepSeek API Key...
if "%DEEPSEEK_API_KEY%"=="" (
    if exist ".env" (
        echo   [✓] 从 .env 加载
    ) else (
        echo   [!] 未配置 — 请在界面中输入或在 .env 中设置
    )
) else (
    echo   [✓] DEEPSEEK_API_KEY 已设置
)

REM ============================================================
REM 启动
REM ============================================================
echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║  Novel2Vid V7.1: http://localhost:8190                  ║
echo ║  IP-Adapter · Ken Burns · CosyVoice2 · 双帧LTX          ║
echo ║  按 Ctrl+C 停止                                          ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

%PYTHON_CMD% main.py
pause
