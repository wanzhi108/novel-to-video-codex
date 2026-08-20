"""
ComfyUI API 客户端服务
"""
import json, time, asyncio, logging
from pathlib import Path
import httpx

logger = logging.getLogger("novel2vid")

from ..config import (
    COMFYUI_URL, COMFYUI_MODELS_DIR, COMFYUI_TIMEOUT_IMAGE, COMFYUI_TIMEOUT_VIDEO,
    COMFYUI_POLL_INTERVAL, MIN_SAFETENSORS_SIZE, KNOWN_MODEL_SIZES, OUTPUT_DIR,
)

# 广播函数引用（由 main.py 在初始化时注入）
_broadcast_progress_fn = None

def set_broadcast_progress(fn):
    """注入进度广播函数（避免循环导入）"""
    global _broadcast_progress_fn
    _broadcast_progress_fn = fn


class ComfyUIClient:
    def __init__(self, base_url: str = COMFYUI_URL):
        self.base_url = base_url
        self._last_comfyui_error = ""
        self._last_comfyui_node = ""
        self._last_comfyui_node_id = ""

    async def get_checkpoints(self) -> list[str]:
        """从ComfyUI API获取可用checkpoint列表"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/object_info/CheckpointLoaderSimple")
                resp.raise_for_status()
                data = resp.json()
                cfg = data["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"]
                if isinstance(cfg, list) and len(cfg) > 0:
                    checkpoints = cfg[0] if isinstance(cfg[0], list) else cfg
                else:
                    return []
        except Exception:
            return []
        
        return [c for c in checkpoints if self._validate_checkpoint_file(c)]

    def _validate_checkpoint_file(self, filename: str) -> bool:
        """验证checkpoint文件完整性：大小检查 + SHA256边车文件校验"""
        ckpt_dir = COMFYUI_MODELS_DIR / "checkpoints"
        filepath = ckpt_dir / filename
        
        if not filepath.exists():
            return True
        
        try:
            size = filepath.stat().st_size
        except OSError:
            return True
        
        if size == 0:
            logger.warning(f"[模型校验] 跳过空文件: {filename}")
            return False
        
        if size < MIN_SAFETENSORS_SIZE:
            logger.warning(f"[模型校验] 跳过疑似损坏文件 ({size/1e9:.1f}GB): {filename}")
            return False
        
        for key, expected_size in KNOWN_MODEL_SIZES.items():
            if key.lower() in filename.lower():
                min_size = expected_size * 0.85
                if size < min_size:
                    logger.warning(
                        f"[模型校验] 跳过损坏文件: {filename} "
                        f"(实际{size/1e9:.1f}GB < 预期≥{min_size/1e9:.1f}GB)"
                    )
                    return False
                break
        
        # SHA256 边车文件校验
        sha256_path = filepath.with_suffix(filepath.suffix + ".sha256")
        if sha256_path.exists():
            try:
                expected_hash = sha256_path.read_text().strip().split()[0].lower()
                if len(expected_hash) >= 64:
                    import hashlib
                    hasher = hashlib.sha256()
                    with open(filepath, "rb") as f:
                        while chunk := f.read(8 * 1024 * 1024):
                            hasher.update(chunk)
                    if hasher.hexdigest() != expected_hash:
                        logger.warning(f"[模型校验] SHA256 不匹配: {filename}")
                        return False
            except Exception:
                pass
        
        return True

    @staticmethod
    def find_output_file(outputs: dict, prefer_types: list = None) -> tuple:
        """递归搜索 ComfyUI outputs 中的文件。
        
        Returns:
            (filename, subfolder, file_type) 或 (None, "", "")
        """
        if prefer_types is None:
            prefer_types = ["gifs", "videos", "images"]
        
        def _search(data: dict, depth: int = 0) -> list:
            results = []
            if depth > 10 or not isinstance(data, dict):
                return results
            for key, val in data.items():
                if key in ("images", "gifs", "videos") and isinstance(val, list) and val:
                    for item in val:
                        if isinstance(item, dict) and "filename" in item:
                            results.append((item["filename"], item.get("subfolder", ""), key, depth))
                elif isinstance(val, dict):
                    results.extend(_search(val, depth + 1))
                elif isinstance(val, list):
                    for v in val:
                        if isinstance(v, dict):
                            results.extend(_search(v, depth + 1))
            return results
        
        all_results = _search(outputs)
        if not all_results:
            for node_id, node_out in outputs.items():
                if isinstance(node_out, dict):
                    for key in prefer_types:
                        if key in node_out and node_out[key]:
                            info = node_out[key][0]
                            if isinstance(info, dict) and "filename" in info:
                                return info["filename"], info.get("subfolder", ""), key
            return None, "", ""
        
        type_order = {t: i for i, t in enumerate(prefer_types)}
        all_results.sort(key=lambda x: (type_order.get(x[2], 99), x[3]))
        best = all_results[0]
        return best[0], best[1], best[2]

    async def get_models(self) -> dict:
        """获取所有可用模型列表（图片+视频+VAE）"""
        result = {
            "checkpoints": await self.get_checkpoints(),
            "vae": await self._get_list("VAELoader", "vae_name"),
            "loras": await self._get_list("LoraLoader", "lora_name"),
            "ipadapter": await self._get_list("IPAdapterModelLoader", "ipadapter_file"),
            "clip_vision": await self._get_list("CLIPVisionLoader", "clip_name"),
        }
        return result

    async def _get_list(self, node_type: str, field: str) -> list:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/object_info/{node_type}")
                resp.raise_for_status()
                data = resp.json()
                cfg = data[node_type]["input"]["required"].get(field)
                if isinstance(cfg, list) and len(cfg) > 0:
                    return cfg[0] if isinstance(cfg[0], list) else cfg
                return []
        except Exception:
            return []

    async def interrupt(self):
        """中断当前ComfyUI任务"""
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{self.base_url}/interrupt")
            return resp.status_code == 200

    async def get_queue(self) -> dict:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{self.base_url}/queue")
            resp.raise_for_status()
            return resp.json()

    async def submit_workflow(self, workflow: dict) -> str:
        payload = json.dumps({"prompt": workflow}, ensure_ascii=False).encode("utf-8")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/prompt",
                content=payload,
                headers={"Content-Type": "application/json"}
            )
            resp.raise_for_status()
            return resp.json()["prompt_id"]

    async def wait_for_result(self, prompt_id: str, job_id: str = "", 
                              scene_id: int = 0, timeout: int = COMFYUI_TIMEOUT_IMAGE) -> dict:
        """等待 ComfyUI 任务完成，带进度推送"""
        start = time.time()
        self._last_comfyui_error = ""
        self._last_comfyui_node = ""
        self._last_comfyui_node_id = ""
        last_progress_push = 0.0
        
        print(f"[INFO] 等待任务: {prompt_id[:20]}... timeout={timeout}s", flush=True)
        
        async with httpx.AsyncClient(timeout=10) as client:
            while time.time() - start < timeout:
                try:
                    resp = await client.get(f"{self.base_url}/history/{prompt_id}")
                    if resp.status_code == 200:
                        data = resp.json()
                        if prompt_id in data:
                            entry = data[prompt_id]
                            status = entry.get("status", {})
                            
                            if status.get("completed", False):
                                print(f"[INFO] ✅ 任务完成: {prompt_id[:20]}...", flush=True)
                                if job_id and _broadcast_progress_fn:
                                    await _broadcast_progress_fn(job_id, {
                                        "type": "comfyui_progress",
                                        "scene_id": scene_id,
                                        "comfyui_progress": 1.0,
                                        "comfyui_status": "completed"
                                    })
                                return entry
                            
                            if status.get("status_str") == "error":
                                msgs = status.get("messages", [])
                                for m in msgs:
                                    if m[0] == "execution_error":
                                        err = m[1]
                                        self._last_comfyui_error = err.get('exception_message', '未知错误')
                                        self._last_comfyui_node = err.get('node_type', '?')
                                        self._last_comfyui_node_id = err.get('node_id', '?')
                                raise RuntimeError(
                                    f"ComfyUI [{self._last_comfyui_node_id}] {self._last_comfyui_node} 失败: "
                                    f"{self._last_comfyui_error[:300]}"
                                )
                            
                            if job_id and (time.time() - last_progress_push) > 1.0:
                                last_progress_push = time.time()
                                try:
                                    q_resp = await client.get(f"{self.base_url}/queue")
                                    if q_resp.status_code == 200:
                                        q = q_resp.json()
                                        running = q.get("queue_running", [])
                                        pending = q.get("queue_pending", [])
                                        is_running = any(r[1] == prompt_id for r in running)
                                        total_ahead = len(pending)
                                        if _broadcast_progress_fn:
                                            await _broadcast_progress_fn(job_id, {
                                                "type": "comfyui_progress",
                                                "scene_id": scene_id,
                                                "comfyui_progress": 0.5 if is_running else 0.1,
                                                "comfyui_status": "running" if is_running else "queued",
                                                "comfyui_queue_ahead": total_ahead
                                            })
                                except Exception:
                                    pass
                
                except Exception as e:
                    if "ComfyUI" in str(e) or "执行失败" in str(e):
                        raise
                    print(f"[WARN] 轮询错误: {e}", flush=True)
                
                await asyncio.sleep(COMFYUI_POLL_INTERVAL)
            
            raise TimeoutError(f"ComfyUI 工作流超时 ({timeout}s): {prompt_id}")

    async def upload_image(self, image_path: str, overwrite: bool = True) -> str:
        filename = Path(image_path).name
        async with httpx.AsyncClient(timeout=30) as client:
            with open(image_path, "rb") as f:
                resp = await client.post(
                    f"{self.base_url}/upload/image",
                    files={"image": (filename, f, "image/png")},
                    data={"overwrite": str(overwrite).lower()}
                )
            resp.raise_for_status()
            return resp.json().get("name", filename)

    async def download_output(self, filename: str, subfolder: str = "",
                              output_type: str = "output", save_dir: Path = OUTPUT_DIR) -> str:
        async with httpx.AsyncClient(timeout=900) as client:
            resp = await client.get(
                f"{self.base_url}/view",
                params={"filename": filename, "subfolder": subfolder, "type": output_type}
            )
            resp.raise_for_status()
            save_path = save_dir / filename
            save_path.write_bytes(resp.content)
            return str(save_path)
