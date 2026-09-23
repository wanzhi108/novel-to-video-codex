"""
╔══════════════════════════════════════════════════════════╗
║  墨影流光 · LuminaForge v12.1                            ║
║  字里乾坤 · 光影成诗                                      ║
║  ——————————————————————————————————                     ║
║  pywebview 重写 · 内嵌 WebView2 · 进程管理增强            ║
╚══════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# PyInstaller 多进程支持：必须在最前面调用
import multiprocessing
multiprocessing.freeze_support()

import sys
import os
import json
import time
import threading
import subprocess
import urllib.request
import webbrowser
import queue
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════
#  常量 & 路径
# ═══════════════════════════════════════════════════════════
def _get_base_dir() -> Path:
    """获取应用基础目录：开发时用仓库根，打包后用 exe 所在目录（可写）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_resource_dir() -> Path:
    """获取资源目录（只读）：打包后在 _MEIPASS，开发时在仓库根"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent

BASE_DIR = _get_base_dir()
RESOURCE_DIR = _get_resource_dir()
MAIN_SCRIPT = RESOURCE_DIR / "scripts" / "main.py"
CONFIG_FILE = BASE_DIR / "launcher_config.json"

PROJECT_DIR = BASE_DIR  # 保持旧引用兼容

# 确保 RESOURCE_DIR / scripts 在 sys.path 中，打包后 import scripts.main / storage / video_engine 才能找到
if str(RESOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(RESOURCE_DIR))
if str(RESOURCE_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(RESOURCE_DIR / "scripts"))

# 窗口化 .exe 中 sys.stdout/stderr 为 None，uvicorn 日志会崩溃；重定向到日志文件
if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
    try:
        _log_dir = BASE_DIR / "_logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
        sys.stdout = open(str(_log_dir / "stdout.log"), "a", encoding="utf-8")
        sys.stderr = open(str(_log_dir / "stderr.log"), "a", encoding="utf-8")
    except Exception:
        pass

APP_NAME      = "墨影流光"
APP_NAME_EN   = "LuminaForge"
APP_VERSION   = "v12.2"
APP_TAGLINE   = "字里乾坤 · 光影成诗"

# 品牌资源路径（开发模式在项目根，打包后在 _MEIPASS）
ICON_PATH      = RESOURCE_DIR / "resources" / "luminaforge.ico"
TRAY_ICON_PATH = RESOURCE_DIR / "resources" / "luminaforge_tray.png"
PREVIEW_PATH   = RESOURCE_DIR / "resources" / "luminaforge_preview.png"

DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_SERVER_PORT = 8190

# ═══════════════════════════════════════════════════════════
#  Python 探测
# ═══════════════════════════════════════════════════════════
def _find_python_exe() -> str:
    candidates = [
        str(BASE_DIR / "venv" / "Scripts" / "python.exe"),
        str(BASE_DIR / ".venv" / "Scripts" / "python.exe"),
    ]
    env_py = os.environ.get("PYTHON_EXE", "")
    if env_py:
        candidates.insert(0, env_py)
    if not getattr(sys, "frozen", False):
        candidates.insert(0, sys.executable)

    for exe in candidates:
        if Path(exe).exists() and _has_module(exe, "fastapi"):
            return exe

    return "python" if getattr(sys, "frozen", False) else (sys.executable or "python")

def _has_module(exe: str, mod: str) -> bool:
    if getattr(sys, "frozen", False) and Path(exe).resolve() == Path(sys.executable).resolve():
        return False
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run([exe, "-c", f"import {mod}"],
                          capture_output=True, timeout=5,
                          creationflags=flags)
        return r.returncode == 0
    except Exception:
        return False

PYTHON_EXE = _find_python_exe()

# ─── 可选依赖 ───
try: import psutil; HAS_PSUTIL = True
except ImportError: HAS_PSUTIL = False

# ═══════════════════════════════════════════════════════════
#  配置系统
# ═══════════════════════════════════════════════════════════
@dataclass
class LauncherConfig:
    comfyui_url: str = DEFAULT_COMFYUI_URL
    port: int = DEFAULT_SERVER_PORT
    api_key: str = ""
    quality: str = "hires"
    model: str = "animagine-xl-4.0"
    ipadapter: bool = True
    auto_comfyui: bool = False
    auto_start_server: bool = True
    auto_cosyvoice: bool = True
    active_preset: str = "青瓷绘卷"

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in [
            "comfyui_url", "port", "api_key", "quality", "model",
            "ipadapter", "auto_comfyui", "auto_start_server", "auto_cosyvoice",
            "active_preset"
        ]}

    @classmethod
    def from_dict(cls, d: dict) -> "LauncherConfig":
        c = cls()
        for k in c.to_dict():
            if k in d: setattr(c, k, d[k])
        return c

    def load(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                for k in self.to_dict():
                    if k in d: setattr(self, k, d[k])
                return True
        except Exception:
            pass
        return False

    def save(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
#  日志缓冲
# ═══════════════════════════════════════════════════════════
class LogBuffer:
    MAX = 500
    def __init__(self):
        self._entries: List[tuple] = []
        self._lock = threading.Lock()
    def add(self, msg: str, tag: str = "info"):
        ts = time.strftime("%H:%M:%S")
        with self._lock:
            self._entries.append((ts, msg, tag))
            if len(self._entries) > self.MAX:
                self._entries = self._entries[-self.MAX:]
    def get_all(self) -> List[tuple]:
        with self._lock: return list(self._entries)
    def clear(self):
        with self._lock: self._entries.clear()


# ═══════════════════════════════════════════════════════════
#  系统托盘管理（可选：需要 pystray + PIL）
# ═══════════════════════════════════════════════════════════
class TrayManager:
    """v12.1 新增：系统托盘图标与右键菜单。未安装 pystray 时静默禁用。"""

    def __init__(self, app: "LauncherApp"):
        self.app = app
        self._icon = None
        self._visible = True
        self._has_pystray = False
        try:
            import pystray
            self._pystray = pystray
            self._has_pystray = True
        except Exception:
            self._pystray = None

    def _load_image(self):
        from PIL import Image as PILImage, ImageDraw
        candidates = [
            TRAY_ICON_PATH,
            PREVIEW_PATH,
            ICON_PATH,
        ]
        for p in candidates:
            if p.exists():
                img = PILImage.open(str(p))
                # 托盘图标统一缩放到 32x32
                if img.size != (32, 32):
                    img = img.resize((32, 32), PILImage.Resampling.LANCZOS)
                return img
        # 兜底：创建纯色图标
        img = PILImage.new("RGBA", (32, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        ds = 10
        cx = cy = 16
        d.polygon([(cx, cy - ds), (cx + ds, cy), (cx, cy + ds), (cx - ds, cy)],
                  fill=(200, 165, 95, 255))
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(30, 28, 36, 255))
        return img

    def start(self):
        if not self._has_pystray or self._icon is not None:
            return

        img = self._load_image()

        def _show():
            if self.app._webview_window:
                try:
                    self.app._webview_window.show()
                    self.app._webview_window.restore()
                except Exception:
                    pass
            self._visible = True

        def _hide():
            if self.app._webview_window:
                try:
                    self.app._webview_window.hide()
                except Exception:
                    pass
            self._visible = False

        def _toggle():
            if self._visible:
                _hide()
            else:
                _show()

        def _start_server(item):
            self.app.pm.start_server()

        def _stop_server(item):
            self.app.pm.stop_server()

        def _exit(item):
            self.app._exit_app()

        self._icon = self._pystray.Icon(
            "luminaforge",
            img,
            title=f"{APP_NAME} {APP_VERSION}",
            menu=self._pystray.Menu(
                self._pystray.MenuItem("显示/隐藏", _toggle, default=True),
                self._pystray.MenuItem("在浏览器打开", lambda i: self.app._api.open_in_browser()),
                self._pystray.Menu.SEPARATOR,
                self._pystray.MenuItem("启动服务", _start_server),
                self._pystray.MenuItem("停止服务", _stop_server),
                self._pystray.Menu.SEPARATOR,
                self._pystray.MenuItem("退出", _exit),
            ),
        )
        threading.Thread(target=self._icon.run, daemon=True).start()

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def update_title(self, text: str):
        if self._icon:
            try:
                self._icon.title = text
            except Exception:
                pass

# ═══════════════════════════════════════════════════════════
#  进程管理器 — 核心逻辑（不依赖任何 UI 框架）
# ═══════════════════════════════════════════════════════════
class ProcessManager:
    """管理 FastAPI 服务器和 ComfyUI 进程的生命周期"""

    def __init__(self, config: LauncherConfig, log: LogBuffer):
        self.config = config
        self.log = log
        self.server_process: Optional[subprocess.Popen] = None
        self.comfyui_process: Optional[subprocess.Popen] = None
        self.cosyvoice_process: Optional[subprocess.Popen] = None
        self.is_cosyvoice_running = False
        self._uvicorn_server = None
        self.is_server_running = False
        self.is_comfyui_running = False
        self._health_stop = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        self._on_server_ready: Optional[Callable] = None
        self._on_server_failed: Optional[Callable] = None
        self._on_comfyui_ready: Optional[Callable] = None
        self._on_status_change: Optional[Callable] = None

    def _log(self, msg: str, tag: str = "info"):
        self.log.add(msg, tag)
        print(f"[{tag.upper()}] {msg}", flush=True)

    # ─── 端口管理 ──────────────────────────────────────────
    def _kill_port(self, port: int):
        """杀掉占用指定端口的进程"""
        if sys.platform != "win32": return
        try:
            flags = subprocess.CREATE_NO_WINDOW
            r = subprocess.run(['netstat', '-ano'], capture_output=True,
                              timeout=5, text=True, creationflags=flags)
            for line in r.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = line.split()[-1]
                    if pid.isdigit():
                        subprocess.run(['taskkill', '/F', '/PID', pid],
                                      capture_output=True, timeout=5,
                                      creationflags=flags)
        except Exception:
            pass

    # ─── 服务器管理 ────────────────────────────────────────
    def start_server(self):
        """启动 FastAPI 服务器"""
        if self.is_server_running:
            self._log("服务器已在运行", "warn")
            return

        port = self.config.port
        comfyui_url = self.config.comfyui_url
        api_key = self.config.api_key or os.environ.get("DEEPSEEK_API_KEY", "")

        self._log("正在启动服务器...", "info")

        # 自动启动 ComfyUI
        if self.config.auto_comfyui:
            try:
                urllib.request.urlopen(f"{self.config.comfyui_url}/system_stats", timeout=3)
            except Exception:
                self.start_comfyui()

        # 自动启动 CosyVoice2（端口 50000）
        if self.config.auto_cosyvoice:
            try:
                urllib.request.urlopen("http://localhost:50000/", timeout=3)
            except Exception:
                self.start_cosyvoice()

        def _run():
            error_log_file = BASE_DIR / "server_error.log"
            try:
                self._kill_port(port)
                env = os.environ.copy()
                env["COMFYUI_URL"] = comfyui_url
                # 冻结模式：内嵌服务通过 import main 时读取 os.environ 获取 key，
                # 仅写入本地 env 字典不会传递到内嵌进程，必须同步到 os.environ，
                # 否则 DEEPSEEK_API_KEY 永远为空 -> generate-prompts 调 DeepSeek 失败 500。
                if api_key:
                    env["DEEPSEEK_API_KEY"] = api_key
                    os.environ["DEEPSEEK_API_KEY"] = api_key
                if comfyui_url:
                    os.environ["COMFYUI_URL"] = comfyui_url
                env["PYTHONIOENCODING"] = "utf-8"

                if getattr(sys, "frozen", False):
                    # 打包模式：在独立线程中直接启动 uvicorn
                    self._log("正在启动服务器（嵌入模式）...", "info")

                    def _uvicorn_run():
                        try:
                            import asyncio
                            import uvicorn
                            from scripts import main as main_module
                            asyncio.set_event_loop(asyncio.new_event_loop())
                            config = uvicorn.Config(
                                main_module.app, host="0.0.0.0", port=port,
                                log_level="info", loop="asyncio"
                            )
                            server = uvicorn.Server(config)
                            self._uvicorn_server = server
                            server.run()
                        except Exception as exc:
                            import traceback
                            full_trace = traceback.format_exc()
                            try:
                                with open(str(error_log_file), "w", encoding="utf-8") as f:
                                    f.write(f"嵌入服务器错误: {exc}\n{full_trace}")
                            except Exception:
                                pass
                            self._log(f"嵌入服务器错误: {exc}", "err")

                    threading.Thread(target=_uvicorn_run, daemon=True).start()
                else:
                    # 开发模式：用 subprocess 启动 main.py
                    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    self.server_process = subprocess.Popen(
                        [PYTHON_EXE, "-u", str(MAIN_SCRIPT)],
                        cwd=str(BASE_DIR), env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        creationflags=flags)

                    def _drain():
                        try:
                            for raw in iter(self.server_process.stdout.readline, b""):
                                line = raw.decode("utf-8", errors="replace").rstrip()
                                if line:
                                    self._log(line, "info")
                        except Exception:
                            pass
                    threading.Thread(target=_drain, daemon=True).start()

                    self._log(f"PID: {self.server_process.pid}", "ok")

                # 等待服务器启动，最多 60 秒
                for i in range(60):
                    time.sleep(1)
                    try:
                        req = urllib.request.Request(f"http://localhost:{port}/api/health")
                        if json.loads(urllib.request.urlopen(req, timeout=2).read()).get("status") == "ok":
                            self.is_server_running = True
                            self._on_server_ready_event()
                            return
                    except Exception:
                        pass
                    if i % 10 == 0 and i > 0:
                        self._log(f"等待服务器启动... {i}s", "info")

                self._log("服务器启动超时", "err")
                self._on_server_failed_event()
            except Exception as exc:
                import traceback
                full_trace = traceback.format_exc()
                self._log(f"启动错误: {exc}\n{full_trace[-300:]}", "err")
                self._on_server_failed_event()

        threading.Thread(target=_run, daemon=True).start()

    def _on_server_ready_event(self):
        """服务器就绪回调"""
        self._log("服务器启动成功", "ok")
        self._start_health_monitor()
        if self._on_server_ready:
            self._on_server_ready()
        if self._on_status_change:
            self._on_status_change("server", True)

    def _on_server_failed_event(self):
        """服务器启动失败回调"""
        if self._on_server_failed:
            self._on_server_failed()
        if self._on_status_change:
            self._on_status_change("server", False)

    def stop_server(self):
        """停止 FastAPI 服务器"""
        if getattr(sys, "frozen", False):
            if hasattr(self, "_uvicorn_server") and self._uvicorn_server:
                try:
                    self._uvicorn_server.should_exit = True
                except Exception:
                    pass
        elif self.server_process:
            try:
                self.server_process.terminate()
            except Exception:
                pass

        self._kill_port(self.config.port)
        self.server_process = None
        self.is_server_running = False
        self._stop_health_monitor()
        self._log("服务器已停止", "info")
        if self._on_status_change:
            self._on_status_change("server", False)

    # ─── ComfyUI 管理 ─────────────────────────────────────
    def start_comfyui(self):
        """启动 ComfyUI"""
        if self.is_comfyui_running:
            self._log("ComfyUI 已在运行", "warn")
            return

        comfyui_paths = []
        env_comfyui = os.environ.get("COMFYUI_PATH", "")
        if env_comfyui:
            comfyui_paths.append(Path(env_comfyui))
        comfyui_paths.append(BASE_DIR / "ComfyUI")
        comfyui_dir = None
        for p in comfyui_paths:
            if (p / "main.py").exists():
                comfyui_dir = p; break
        if not comfyui_dir:
            self._log("未找到 ComfyUI", "err")
            return

        self._log(f"启动 ComfyUI: {comfyui_dir.name}", "info")

        def _run():
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONPATH"] = ""
                env["WANDB_DISABLED"] = "true"
                env["WANDB_MODE"] = "disabled"
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                comfyui_python = comfyui_dir.parent / "python" / "python.exe"
                if not comfyui_python.exists():
                    comfyui_python = Path(PYTHON_EXE)
                self.comfyui_process = subprocess.Popen(
                    [str(comfyui_python), "-u", "-s", str(comfyui_dir / "main.py"),
                     "--lowvram", "--async-offload", "2",
                     "--port", "8188", "--listen", "127.0.0.1"],
                    cwd=str(comfyui_dir), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=flags)

                def _drain():
                    try:
                        for raw in iter(self.comfyui_process.stdout.readline, b""):
                            line = raw.decode("utf-8", errors="replace").rstrip()
                            if line:
                                self._log(f"[CF] {line[:120]}", "info")
                    except Exception:
                        pass
                threading.Thread(target=_drain, daemon=True).start()

                for _ in range(30):
                    time.sleep(2)
                    try:
                        if urllib.request.urlopen(
                            f"{self.config.comfyui_url}/system_stats", timeout=3).status == 200:
                            self.is_comfyui_running = True
                            self._log("ComfyUI 已就绪", "ok")
                            if self._on_status_change:
                                self._on_status_change("comfyui", True)
                            return
                    except Exception:
                        pass
                self._log("ComfyUI 启动超时", "err")
            except Exception as exc:
                self._log(f"ComfyUI 错误: {exc}", "err")

        threading.Thread(target=_run, daemon=True).start()

    def stop_comfyui(self):
        """停止 ComfyUI"""
        if self.comfyui_process:
            try:
                self.comfyui_process.terminate()
            except Exception:
                pass
        self.comfyui_process = None
        self.is_comfyui_running = False
        self._log("ComfyUI 已停止", "info")
        if self._on_status_change:
            self._on_status_change("comfyui", False)

    # ─── CosyVoice2 管理（v12.1 新增：随主服务一同启动） ─────
    def start_cosyvoice(self):
        """启动 CosyVoice2 本地 TTS 服务（端口 50000）。
        路径可经环境变量 COSYVOICE_PATH 覆盖，默认在仓库外/常见安装位置查找。
        """
        if getattr(self, "is_cosyvoice_running", False):
            self._log("CosyVoice2 已在运行", "warn")
            return
        if not hasattr(self, "is_cosyvoice_running"):
            self.is_cosyvoice_running = False

        cosy_root = Path(os.environ.get("COSYVOICE_PATH", ""))
        if not cosy_root:
            cosy_root = BASE_DIR / "CosyVoice2"
        cosy_py = cosy_root / "cosy_env" / "Scripts" / "python.exe"
        cosy_server = cosy_root / "server.py"

        # 若默认路径不存在，回退尝试仓库内/常见安装位置
        if not cosy_py.exists() or not cosy_server.exists():
            for cand in [BASE_DIR / "CosyVoice2",
                         Path(os.environ.get("COSYVOICE_PATH", ""))]:
                if (cand / "cosy_env" / "Scripts" / "python.exe").exists() \
                   and (cand / "server.py").exists():
                    cosy_root = cand
                    cosy_py = cand / "cosy_env" / "Scripts" / "python.exe"
                    cosy_server = cand / "server.py"
                    break

        if not cosy_py.exists() or not cosy_server.exists():
            self._log(f"未找到 CosyVoice2（路径: {cosy_root}），跳过自动启动", "warn")
            return

        self._log(f"启动 CosyVoice2: {cosy_root.name}", "info")

        def _run():
            try:
                env = os.environ.copy()
                # CosyVoice2 走本机服务，去掉代理避免连接异常
                for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
                    env.pop(k, None)
                env["PYTHONIOENCODING"] = "utf-8"

                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                self.cosyvoice_process = subprocess.Popen(
                    [str(cosy_py), str(cosy_server)],
                    cwd=str(cosy_root), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=flags)

                def _drain():
                    try:
                        for raw in iter(self.cosyvoice_process.stdout.readline, b""):
                            line = raw.decode("utf-8", errors="replace").rstrip()
                            if line:
                                self._log(f"[CV] {line[:120]}", "info")
                    except Exception:
                        pass
                threading.Thread(target=_drain, daemon=True).start()

                for _ in range(60):
                    time.sleep(1)
                    try:
                        if urllib.request.urlopen(
                            "http://localhost:50000/", timeout=3).status == 200:
                            self.is_cosyvoice_running = True
                            self._log("CosyVoice2 已就绪 (端口 50000)", "ok")
                            if self._on_status_change:
                                self._on_status_change("cosyvoice", True)
                            return
                    except Exception:
                        pass
                self._log("CosyVoice2 启动超时（仍可在外部手动启动）", "warn")
                self.is_cosyvoice_running = False
            except Exception as exc:
                self._log(f"CosyVoice2 错误: {exc}", "err")
                self.is_cosyvoice_running = False

        threading.Thread(target=_run, daemon=True).start()

    def stop_cosyvoice(self):
        """停止 CosyVoice2 服务"""
        if getattr(self, "cosyvoice_process", None):
            try:
                self.cosyvoice_process.terminate()
            except Exception:
                pass
        self.cosyvoice_process = None
        self.is_cosyvoice_running = False
        self._log("CosyVoice2 已停止", "info")
        if self._on_status_change:
            self._on_status_change("cosyvoice", False)

    # ─── 健康监控（v12 新增：自动重启） ────────────────────
    def _start_health_monitor(self):
        """启动服务器健康监控 — 每 15 秒检查一次，失败自动重启"""
        self._health_stop.clear()

        def _loop():
            consecutive_failures = 0
            while not self._health_stop.is_set():
                self._health_stop.wait(15)
                if self._health_stop.is_set():
                    break
                try:
                    req = urllib.request.Request(
                        f"http://localhost:{self.config.port}/api/health")
                    data = json.loads(urllib.request.urlopen(req, timeout=5).read())
                    if data.get("status") == "ok":
                        consecutive_failures = 0
                    else:
                        raise Exception("unhealthy")
                except Exception:
                    consecutive_failures += 1
                    self._log(f"健康检查失败 ({consecutive_failures}/3)", "warn")
                    if consecutive_failures >= 3:
                        self._log("服务器连续 3 次健康检查失败，尝试自动重启...", "warn")
                        self.is_server_running = False
                        self.stop_server()
                        time.sleep(2)
                        self.start_server()
                        consecutive_failures = 0

        self._health_thread = threading.Thread(target=_loop, daemon=True)
        self._health_thread.start()

    def _stop_health_monitor(self):
        """停止健康监控"""
        self._health_stop.set()
        if self._health_thread:
            self._health_thread.join(timeout=2)

    # ─── 优雅关闭 ─────────────────────────────────────────
    def shutdown(self):
        """优雅关闭所有进程"""
        self._log("正在关闭所有服务...", "info")
        self._stop_health_monitor()
        self.stop_server()
        self.stop_comfyui()
        self.stop_cosyvoice()
        self._log("所有服务已停止", "info")

    # ─── 环境检查 ─────────────────────────────────────────
    def check_environment(self) -> dict:
        """检查所有依赖环境，返回状态字典"""
        result = {
            "comfyui": False,
            "cosyvoice": False,
            "ffmpeg": False,
            "deepseek": False,
            "server": False,
        }

        # ComfyUI
        try:
            req = urllib.request.Request(f"{self.config.comfyui_url}/system_stats")
            data = json.loads(urllib.request.urlopen(req, timeout=5).read())
            result["comfyui"] = True
            dev = data.get("devices", [{}])[0]
            name = dev.get("name", "?")[:30]
            vram = f"{dev.get('vram_total', 0) / 1073741824:.1f}GB"
            self._log(f"ComfyUI: {name} ({vram})", "ok")
        except Exception:
            self._log("ComfyUI 未连接", "warn")

        # CosyVoice
        try:
            req = urllib.request.Request("http://localhost:50000/")
            resp = urllib.request.urlopen(req, timeout=3)
            if resp.status == 200:
                result["cosyvoice"] = True
                self._log("CosyVoice 2 已就绪", "ok")
        except Exception:
            pass

        # FFmpeg
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            r = subprocess.run(["ffmpeg", "-version"], capture_output=True,
                             timeout=5, creationflags=flags)
            if r.returncode == 0:
                result["ffmpeg"] = True
                self._log("FFmpeg 可用", "ok")
        except Exception:
            pass

        # DeepSeek API Key
        if self.config.api_key or os.environ.get("DEEPSEEK_API_KEY"):
            result["deepseek"] = True
            self._log("DeepSeek API Key 已配置", "ok")
        else:
            self._log("DeepSeek API Key 未设置", "warn")

        # 服务器
        try:
            req = urllib.request.Request(f"http://localhost:{self.config.port}/api/health")
            data = json.loads(urllib.request.urlopen(req, timeout=3).read())
            if data.get("status") == "ok":
                result["server"] = True
        except Exception:
            pass

        return result

    # ─── GPU 信息 ─────────────────────────────────────────
    def get_gpu_info(self) -> dict:
        """获取 GPU VRAM 信息"""
        result = {"vram_free": 0, "vram_total": 0, "gpu_temp": 0}
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=flags)
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split(",")
                used = float(parts[0].strip()) / 1024
                total = float(parts[1].strip()) / 1024
                result["vram_free"] = total - used
                result["vram_total"] = total
                result["gpu_temp"] = float(parts[2].strip()) if len(parts) > 2 else 0
        except Exception:
            try:
                req = urllib.request.Request(f"{self.config.comfyui_url}/system_stats")
                data = json.loads(urllib.request.urlopen(req, timeout=3).read())
                dev = data.get("devices", [{}])[0]
                result["vram_total"] = dev.get("vram_total", 0) / 1073741824
                result["vram_free"] = dev.get("vram_free", 0) / 1073741824
            except Exception:
                pass
        return result

    def get_system_info(self) -> dict:
        """获取系统资源信息"""
        info = {"cpu": 0, "ram": 0, "ram_pct": 0}
        if HAS_PSUTIL:
            info["cpu"] = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            info["ram"] = mem.used / 1073741824
            info["ram_pct"] = mem.percent
        info.update(self.get_gpu_info())
        return info


# ═══════════════════════════════════════════════════════════
#  加载页面 HTML（服务器启动前显示）
# ═══════════════════════════════════════════════════════════
LOADING_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>墨影流光 · LuminaForge</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #09090f; color: #e4e0d8;
  font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
  display: flex; align-items: center; justify-content: center;
  height: 100vh; overflow: hidden;
}
.container { text-align: center; }
.logo-wrap {
  width: 96px; height: 96px;
  margin: 0 auto 20px;
  position: relative;
}
.logo-wrap svg {
  width: 100%; height: 100%;
  filter: drop-shadow(0 0 18px rgba(200, 164, 92, 0.35));
}
.brand {
  font-size: 28px; font-weight: 500; letter-spacing: 4px;
  background: linear-gradient(135deg, #c8a45c, #e8d49a);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin-bottom: 6px;
}
.subtitle { font-size: 13px; color: #5a554e; margin-bottom: 36px; }
.spinner {
  width: 42px; height: 42px;
  border: 2.5px solid #1e1e2a; border-top-color: #c8a45c;
  border-radius: 50%; margin: 0 auto 20px;
  animation: spin 1.1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.status { font-size: 13px; color: #8a847a; min-height: 20px; }
.progress-bar {
  width: 260px; height: 3px; background: #1a1a24;
  border-radius: 2px; margin: 16px auto; overflow: hidden;
}
.progress-fill {
  height: 100%; background: linear-gradient(90deg, #c8a45c, #e8d49a);
  border-radius: 2px; transition: width 0.5s ease;
  animation: indeterminate 1.6s ease-in-out infinite;
}
@keyframes indeterminate {
  0% { width: 0%; margin-left: 0%; }
  50% { width: 50%; margin-left: 25%; }
  100% { width: 0%; margin-left: 100%; }
}
.actions { margin-top: 28px; display: flex; gap: 10px; justify-content: center; }
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 18px;
  background: #c8a45c; color: #0a0a10; border: none; border-radius: 6px;
  font-size: 12px; cursor: pointer; font-family: inherit; transition: .2s;
}
.btn:hover { background: #e0c278; }
.btn.secondary { background: transparent; color: #8a847a; border: 1px solid #2a2a38; }
.btn.secondary:hover { background: #1a1a24; color: #e4e0d8; }
.footer { position: absolute; bottom: 22px; left: 0; right: 0; text-align: center; font-size: 11px; color: #3a3530; }
</style>
</head>
<body>
<div class="container">
  <div class="logo-wrap">
    <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="4" y="4" width="56" height="56" rx="14" fill="#12121a" stroke="#c8a45c" stroke-width="1.5"/>
      <path d="M32 14L48 32L32 50L16 32L32 14Z" fill="url(#gold)"/>
      <defs>
        <linearGradient id="gold" x1="16" y1="14" x2="48" y2="50" gradientUnits="userSpaceOnUse">
          <stop stop-color="#c8a45c"/>
          <stop offset="1" stop-color="#e8d49a"/>
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="5" fill="#1a1a24"/>
      <circle cx="33.5" cy="30.5" r="1.5" fill="white" fill-opacity="0.6"/>
    </svg>
  </div>
  <div class="brand">墨影流光</div>
  <div class="subtitle">LuminaForge v12.2 · 字里乾坤 · 光影成诗</div>
  <div class="spinner"></div>
  <div class="progress-bar"><div class="progress-fill"></div></div>
  <div class="status" id="status">正在启动服务，请稍候...</div>
  <div class="actions">
    <button class="btn" onclick="window.pywebview.api.open_in_browser()">浏览器打开</button>
    <button class="btn secondary" onclick="window.pywebview.api.open_output_dir()">输出目录</button>
    <button class="btn secondary" onclick="window.pywebview.api.minimize_to_tray()">最小化到托盘</button>
  </div>
</div>
<div class="footer">双击托盘图标可恢复窗口</div>
<script>
let retryCount = 0;
const maxRetries = 60;
const APP_URL = "{{APP_URL}}";
function updateStatus(text) {
  const el = document.getElementById('status');
  if (el) el.textContent = text;
}
function checkServer() {
  retryCount++;
  if (retryCount > maxRetries) {
    updateStatus('服务器启动超时，请检查日志');
    return;
  }
  if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.get_status) {
    updateStatus('正在初始化启动器...');
    setTimeout(checkServer, 1000);
    return;
  }
  window.pywebview.api.get_status()
    .then(function(data) {
      if (data && data.server) {
        updateStatus('服务器已就绪，正在加载界面...');
        setTimeout(function() { window.location.href = APP_URL; }, 500);
      } else {
        updateStatus('正在启动服务，请稍候... (第 ' + retryCount + ' 秒)');
        setTimeout(checkServer, 1000);
      }
    })
    .catch(function() {
      updateStatus('正在启动服务，请稍候...');
      setTimeout(checkServer, 1000);
    });
}
checkServer();
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════
#  pywebview API — 暴露给前端 JavaScript 调用
# ═══════════════════════════════════════════════════════════
class LauncherAPI:
    """pywebview JS-Python 桥接 API"""

    def __init__(self, pm: ProcessManager, app: Optional["LauncherApp"] = None):
        self.pm = pm
        self.app = app

    def start_server(self):
        """启动服务器"""
        self.pm.start_server()
        return {"status": "starting"}

    def stop_server(self):
        """停止服务器"""
        self.pm.stop_server()
        return {"status": "stopped"}

    def start_comfyui(self):
        """启动 ComfyUI"""
        self.pm.start_comfyui()
        return {"status": "starting"}

    def stop_comfyui(self):
        """停止 ComfyUI"""
        self.pm.stop_comfyui()
        return {"status": "stopped"}

    def get_status(self):
        """获取服务状态"""
        return {
            "server": self.pm.is_server_running,
            "comfyui": self.pm.is_comfyui_running,
        }

    def get_system_info(self):
        """获取系统资源信息"""
        return self.pm.get_system_info()

    def get_logs(self):
        """获取日志"""
        return [{"ts": ts, "msg": msg, "tag": tag}
                for ts, msg, tag in self.pm.log.get_all()[-100:]]

    def open_in_browser(self):
        """在系统浏览器中打开"""
        url = f"http://localhost:{self.pm.config.port}"
        webbrowser.open(url)
        return {"status": "ok"}

    def open_output_dir(self):
        """打开输出目录"""
        out = BASE_DIR / "output"
        out.mkdir(exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(out))
        return {"status": "ok"}

    def get_config(self):
        """获取配置"""
        return self.pm.config.to_dict()

    def save_config(self, config_json):
        """保存配置"""
        try:
            if isinstance(config_json, str):
                config_json = json.loads(config_json)
            for k, v in config_json.items():
                if hasattr(self.pm.config, k):
                    setattr(self.pm.config, k, v)
            self.pm.config.save()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    def minimize_to_tray(self):
        """最小化到系统托盘（v12.1）"""
        if self.app and self.app._webview_window:
            try:
                self.app._webview_window.hide()
                self.app.tray._visible = False
            except Exception as e:
                return {"status": "error", "msg": str(e)}
        return {"status": "ok"}

    def show_from_tray(self):
        """从系统托盘恢复窗口（v12.1）"""
        if self.app and self.app._webview_window:
            try:
                self.app._webview_window.show()
                self.app._webview_window.restore()
                self.app.tray._visible = True
            except Exception as e:
                return {"status": "error", "msg": str(e)}
        return {"status": "ok"}

    def quit_app(self):
        """完全退出应用（v12.1）"""
        if self.app:
            self.app._exit_app()
        return {"status": "ok"}


# ═══════════════════════════════════════════════════════════
#  主应用
# ═══════════════════════════════════════════════════════════
class LauncherApp:
    """v12 Launcher — pywebview 内嵌 WebView2"""

    def __init__(self):
        self.config = LauncherConfig()
        self.config.load()
        self.log_buffer = LogBuffer()
        self.pm = ProcessManager(self.config, self.log_buffer)
        self.tray = TrayManager(self)
        self._api = None

        # 回调
        self.pm._on_status_change = self._on_status_change

        self._webview_window = None
        self._is_shutting_down = False

    def _on_status_change(self, service: str, running: bool):
        """服务状态变化回调"""
        status = "running" if running else "stopped"
        self.log_buffer.add(f"{service} {status}", "info" if running else "warn")
        if self.tray._icon:
            self.tray.update_title(f"{APP_NAME} {APP_VERSION} — {service}: {status}")

    def _exit_app(self):
        """完全退出应用：停止托盘、关闭窗口、停止服务"""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            if self._webview_window:
                self._webview_window.destroy()
        except Exception:
            pass
        self.pm.shutdown()
        try:
            sys.exit(0)
        except Exception:
            pass

    def run(self):
        """启动 Launcher"""
        self.log_buffer.add(f"✦ {APP_NAME} {APP_VERSION} — {APP_TAGLINE}", "info")
        self.log_buffer.add(f"  Python: {Path(PYTHON_EXE).name}", "info")

        # 环境检查（后台线程）
        def _init_checks():
            time.sleep(1)
            self.pm.check_environment()
            # 自动启动服务器
            if self.config.auto_start_server:
                time.sleep(1)
                self.pm.start_server()

        threading.Thread(target=_init_checks, daemon=True).start()

        # 尝试使用 pywebview
        try:
            import webview
            self._run_pywebview(webview)
        except ImportError:
            self._run_browser_fallback()

    def _run_pywebview(self, webview):
        """使用 pywebview 内嵌 WebView2"""
        self._api = LauncherAPI(self.pm, self)
        api = self._api

        # 启动系统托盘
        self.tray.start()

        # 创建窗口
        port = self.config.port
        server_url = f"http://localhost:{port}"

        # 先用加载页面，服务器就绪后自动跳转
        html = LOADING_HTML.replace("{{APP_URL}}", server_url)
        self._webview_window = webview.create_window(
            title=f"{APP_NAME} · {APP_NAME_EN} {APP_VERSION}",
            html=html,
            js_api=api,
            width=1400,
            height=900,
            min_size=(1024, 680),
            text_select=True,
            confirm_close=True,
        )

        # 服务器就绪后自动跳转到真实应用页面（兜底，防止 JS 失败）
        def _on_server_ready():
            try:
                self._webview_window.load_url(server_url)
            except Exception:
                pass
        self.pm._on_server_ready = _on_server_ready

        # 设置窗口关闭回调
        def _on_closing():
            if not self._is_shutting_down:
                self._is_shutting_down = True
                self.tray.stop()
                self.pm.shutdown()

        self._webview_window.events.closing += _on_closing

        # 启动 webview
        webview.start(debug=False, http_server=True)

        # webview 关闭后，确保所有进程停止
        if not self._is_shutting_down:
            self._is_shutting_down = True
            self.tray.stop()
            self.pm.shutdown()

    def _run_browser_fallback(self):
        """pywebview 不可用时，回退到浏览器模式"""
        print("[Launcher] pywebview 未安装，回退到浏览器模式", flush=True)
        self.log_buffer.add("pywebview 未安装，使用浏览器模式", "warn")

        # 启动服务器
        self.pm.start_server()

        # 等待服务器就绪后打开浏览器
        def _open_browser():
            for _ in range(60):
                time.sleep(1)
                try:
                    req = urllib.request.Request(
                        f"http://localhost:{self.config.port}/api/health")
                    data = json.loads(urllib.request.urlopen(req, timeout=2).read())
                    if data.get("status") == "ok":
                        url = f"http://localhost:{self.config.port}"
                        webbrowser.open(url)
                        print(f"[Launcher] 浏览器已打开: {url}", flush=True)
                        return
                except Exception:
                    pass
            print("[Launcher] 服务器启动超时", flush=True)

        threading.Thread(target=_open_browser, daemon=True).start()

        # 保持主线程运行
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.pm.shutdown()


# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = LauncherApp()
    app.run()
