# -*- mode: python ; coding: utf-8 -*-
# LuminaForge (墨影流光) v12.1 - PyInstaller 构建配置
# v12.1: pywebview + pystray 系统托盘 + SQLite 存储 + video_engine 8模式 + 导入导出

import sys
from pathlib import Path

project_dir = Path(".").resolve()

a = Analysis(
    ['scripts/launcher.py'],
    pathex=[str(project_dir), str(project_dir / "scripts")],
    binaries=[],
    datas=[
        # Web 前端 (v12.0 React 构建产物，优先于 static/)
        ('web/dist', 'web/dist'),
        # 旧版前端 (兼容回退)
        ('static', 'static'),
        # ComfyUI 工作流
        ('comfyui', 'comfyui'),
        # 后端脚本（包含 cloud_video.py 等运行时模块）
        ('scripts', 'scripts'),
        # P6: 工业引擎与质量门模块
        ('engines', 'engines'),
        ('quality', 'quality'),
        ('config', 'config'),
        # 默认配置模板（exe 旁放 settings.yaml 可覆盖）
        ('settings.yaml', '.'),
        # 环境配置模板
        ('.env.example', '.'),
        # app 模块
        ('app', 'app'),
    ],
    hiddenimports=[
        'scripts.main',
        # v12.0: pywebview (内嵌 WebView2)
        'webview',
        'webview.platforms',
        'webview.platforms.winforms',
        'webview.util',
        'webview.js',
        'webview.dom',
        # pywebview 依赖 (pythonnet / clr_loader / bottle)
        'pythonnet',
        'clr_loader',
        'clr_loader.netcore',
        'bottle',
        'proxy_tools',
        'System',
        'System.Windows.Forms',
        'System.Drawing',
        # v12.0: SQLite 存储
        'storage',
        'sqlite3',
        'aiosqlite',
        # v12.0: 统一视频引擎
        'video_engine',
        # P6: 工业引擎桥接 + 新引擎/质量门模块
        'industrial_bridge',
        # P6.1: Novel-Director 剧本 JSON 桥（CLI，供 ComfyUI 编排层）
        'novel_director_bridge',
        'engines',
        'engines.base',
        'engines.local',
        'engines.quality_loop',
        'quality',
        'quality.gate',
        'quality.visual',
        'config',
        'config.settings',
        'yaml',
        # v12.0: 环境生成器
        'environment_generator',
        # v12.1: 系统托盘
        'pystray',
        'pystray._win32',
        # customtkinter (保留为回退)
        'customtkinter',
        'customtkinter.windows.widgets',
        'customtkinter.windows.widgets.core_widget_classes',
        'customtkinter.windows.widgets.font',
        # FastAPI & uvicorn
        'fastapi',
        'fastapi.middleware',
        'fastapi.staticfiles',
        'uvicorn',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'starlette',
        'starlette.middleware',
        # HTTP
        'httpx',
        'httpcore',
        'h11',
        # WebSocket
        'websockets',
        'websocket',
        'websocket-client',
        # TTS
        'edge_tts',
        'edge_tts.util',
        # Audio
        'pydub',
        'pydub.effects',
        'audioop_lts',
        # Imaging
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL._imaging',
        # Others
        'psutil',
        'dotenv',
        'python_dotenv',
        'aiofiles',
        'aiohttp',
        'aiohttp.client',
        'python_multipart',
        'multipart',
        'pydantic',
        'pydantic.deprecated',
        'certifi',
        'yarl',
        'multidict',
        'frozenlist',
        'aiosignal',
        'requests',
        'numpy',
        # cloud_video (可选)
        'cloud_video',
        # router modules in app/
        'app.config',
        'app.models',
        'app.services.comfyui_client',
        # v12.0: kling_client
        'kling_client',
        # v12.0: clr (pywebview WinForms 依赖)
        'clr',
        'System',
        'System.Windows.Forms',
        'System.Drawing',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'pandas',
        'torch',
        'tensorflow',
        'test',
        'unittest',
        'pdb',
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LuminaForge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    # icon omitted: binary brand assets are not tracked in Git
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    file_version='12.2.0.0',
    product_version='12.2.0',
    product_name='LuminaForge',
    company_name='LuminaForge Studio',
    file_description='墨影流光 · 小说转视频工作台 v12.2',
    version='luminaforge_version_info.txt',
)
