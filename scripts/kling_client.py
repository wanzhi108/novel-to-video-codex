"""
可灵AI (Kling AI) API 客户端
用于文生图 - 生成正面清晰角色脸作为 PuLID 参考图

API 文档:
- 端点: POST https://api-beijing.klingai.com/v1/images/generations
- 认证: Authorization: Bearer <api_key>
- 异步模式: 创建任务 -> 返回 task_id -> 轮询查询结果
"""
import asyncio
import httpx
import json
import os
import time
from pathlib import Path
from typing import Optional

KLING_BASE_URL = "https://api-beijing.klingai.com"
KLING_API_KEY = os.environ.get("KLING_API_KEY", "")


class KlingImageClient:
    """可灵AI 文生图客户端"""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or KLING_API_KEY
        self.base_url = KLING_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def create_image_task(
        self,
        prompt: str,
        negative_prompt: str = "",
        model: str = "kling-image",
        aspect_ratio: str = "1:1",
        n: int = 1,
    ) -> dict:
        """
        创建文生图任务 (异步)
        
        参数:
            prompt: 正向提示词
            negative_prompt: 负向提示词
            model: 模型名称 (kling-image / kling-v2.1 / kling-v2 等)
            aspect_ratio: 宽高比 (1:1 / 9:16 / 16:9 等)
            n: 生成图片数量
        
        返回:
            {"task_id": "xxx", "code": 0, "message": "success"}
            或错误: {"code": 1102, "message": "Account balance not enough"}
        """
        url = f"{self.base_url}/v1/images/generations"
        body = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "aspect_ratio": aspect_ratio,
        }
        if negative_prompt:
            body["negative_prompt"] = negative_prompt

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=self.headers, json=body)
            data = resp.json()

            if resp.status_code != 200:
                return {
                    "error": True,
                    "code": data.get("code", resp.status_code),
                    "message": data.get("message", f"HTTP {resp.status_code}"),
                }

            return data

    async def query_task(self, task_id: str) -> dict:
        """
        查询任务状态和结果
        
        返回:
            成功: {"task_id": "xxx", "status": "succeed", "data": [{"url": "..."}], ...}
            处理中: {"task_id": "xxx", "status": "processing"}
            失败: {"task_id": "xxx", "status": "failed"}
        """
        # 尝试两种可能的查询端点
        for endpoint in [
            f"/v1/images/generations/{task_id}",
            f"/v1/images/tasks/{task_id}",
        ]:
            url = f"{self.base_url}{endpoint}"
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url, headers=self.headers)
                    if resp.status_code == 200:
                        return resp.json()
                    elif resp.status_code == 404:
                        continue  # 尝试下一个端点
                    else:
                        data = resp.json()
                        return {
                            "error": True,
                            "code": data.get("code", resp.status_code),
                            "message": data.get("message", f"HTTP {resp.status_code}"),
                        }
            except Exception:
                continue

        return {"error": True, "code": 404, "message": "无法查询任务状态"}

    async def wait_for_result(
        self,
        task_id: str,
        max_wait: int = 180,
        poll_interval: int = 5,
        on_progress=None,
    ) -> dict:
        """
        轮询等待任务完成
        
        参数:
            task_id: 任务ID
            max_wait: 最大等待秒数
            poll_interval: 轮询间隔秒数
            on_progress: 进度回调 callback(status: str)
        
        返回:
            成功: {"status": "succeed", "images": ["url1", ...]}
            失败: {"status": "failed", "message": "..."}
            超时: {"status": "timeout"}
        """
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            result = await self.query_task(task_id)
            
            if result.get("error"):
                # 查询出错，等待后重试
                await asyncio.sleep(poll_interval)
                continue
            
            status = result.get("status", "").lower()
            
            if on_progress:
                await on_progress(status)
            
            # 终态判断
            if status in ("succeed", "success", "succeeded", "completed"):
                # 提取图片URL
                images = []
                data = result.get("data", [])
                if isinstance(data, list):
                    for item in data:
                        url = item.get("url") if isinstance(item, dict) else None
                        if url:
                            images.append(url)
                
                if not images:
                    # 尝试其他字段
                    output = result.get("output", {})
                    choices = output.get("choices", [])
                    for choice in choices:
                        content = choice.get("message", {}).get("content", [])
                        for c in content:
                            if c.get("type") == "image" and c.get("image"):
                                images.append(c["image"])
                
                return {"status": "succeed", "images": images, "raw": result}
            
            elif status in ("failed", "error"):
                return {
                    "status": "failed",
                    "message": result.get("status_message", "任务失败"),
                    "raw": result,
                }
            
            # 非终态，继续等待
            await asyncio.sleep(poll_interval)
        
        return {"status": "timeout"}

    async def download_image(self, url: str, save_path: str) -> str:
        """下载生成的图片到本地"""
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            
            return save_path

    async def generate_face_image(
        self,
        character_description: str,
        save_dir: str,
        filename: str = "kling_face.png",
        on_progress=None,
    ) -> dict:
        """
        一站式: 生成角色正脸图片并下载到本地
        
        参数:
            character_description: 角色描述
                - 如果是完整英文prompt（含portrait/front view等），直接使用
                - 否则自动拼接正面清晰脸的模板
            save_dir: 保存目录
            filename: 文件名
            on_progress: 进度回调
        
        返回:
            成功: {"status": "succeed", "path": "/path/to/image.png"}
            失败: {"status": "failed", "message": "..."}
        """
        # 判断是否是完整prompt（DeepSeek生成的kling_prompt通常包含这些关键词）
        desc_lower = character_description.lower()
        is_full_prompt = any(kw in desc_lower for kw in ["portrait", "front view", "looking at camera", "face"])
        
        if is_full_prompt:
            # 已是完整prompt，直接使用
            face_prompt = character_description
        else:
            # 拼接正面清晰脸模板
            face_prompt = (
                f"portrait of {character_description}, "
                f"front view, clear face, looking at camera, "
                f"neutral expression, sharp focus, high detail face, "
                f"cinematic lighting, professional photography, 8k quality"
            )
        
        negative = (
            "blurry, low quality, deformed face, side view, back view, "
            "multiple faces, cropped face, covered face, sunglasses, mask, "
            "worst quality, bad anatomy, watermark, text"
        )

        # 创建任务
        if on_progress:
            await on_progress("creating_task")
        
        task_result = await self.create_image_task(
            prompt=face_prompt,
            negative_prompt=negative,
            model="kling-image",
            aspect_ratio="1:1",
            n=1,
        )

        if task_result.get("error"):
            return {
                "status": "failed",
                "message": task_result.get("message", "创建任务失败"),
                "code": task_result.get("code"),
            }

        task_id = task_result.get("task_id")
        if not task_id:
            return {
                "status": "failed",
                "message": f"未返回 task_id: {json.dumps(task_result, ensure_ascii=False)[:200]}",
            }

        print(f"[Kling] 任务已创建: {task_id}", flush=True)

        # 轮询等待结果
        if on_progress:
            await on_progress("waiting")

        result = await self.wait_for_result(
            task_id, max_wait=180, poll_interval=5, on_progress=on_progress
        )

        if result["status"] != "succeed":
            return {
                "status": "failed",
                "message": result.get("message", f"任务{result['status']}"),
            }

        images = result.get("images", [])
        if not images:
            return {"status": "failed", "message": "任务完成但未返回图片URL"}

        # 下载图片
        if on_progress:
            await on_progress("downloading")

        save_path = str(Path(save_dir) / filename)
        await self.download_image(images[0], save_path)

        print(f"[Kling] 角色正脸已保存: {save_path}", flush=True)

        return {
            "status": "succeed",
            "path": save_path,
            "image_url": images[0],
            "task_id": task_id,
        }

    async def generate_character_set(
        self,
        character_description: str,
        save_dir: str,
        character_name: str = "char",
        n_angles: int = 3,
        on_progress=None,
    ) -> dict:
        """
        v12.0: 为角色生成多角度参考图集，用于 PuLID 多参考图输入

        生成角度:
        - 正面 (front view): 清晰正脸，用于 PuLID 主参考
        - 侧面 (side profile): 45度侧面，增强三维一致性
        - 半身 (half body): 上半身含着装，用于 IP-Adapter 服装一致性

        参数:
            character_description: 角色描述 (外貌/着装等)
            save_dir: 保存目录
            character_name: 角色名 (用于文件命名)
            n_angles: 角度数量 (1=仅正面, 2=正面+侧面, 3=正面+侧面+半身)
            on_progress: 进度回调 callback(angle: str, status: str)

        返回:
            成功: {"status": "succeed", "paths": ["front.png", "side.png", "halfbody.png"]}
            失败: {"status": "failed", "message": "..."}
        """
        angle_configs = [
            {
                "name": "front",
                "filename": f"{character_name}_front.png",
                "prompt_suffix": "front view, clear face, looking at camera, neutral expression, sharp focus, high detail face, cinematic lighting, professional photography, 8k quality",
            },
            {
                "name": "side",
                "filename": f"{character_name}_side.png",
                "prompt_suffix": "side profile view, 45 degree angle, half face visible, same person, consistent appearance, cinematic lighting, 8k quality",
            },
            {
                "name": "halfbody",
                "filename": f"{character_name}_halfbody.png",
                "prompt_suffix": "half body shot, upper body visible, same person, consistent face and clothing, standing pose, cinematic lighting, 8k quality",
            },
        ]

        negative = (
            "blurry, low quality, deformed face, back view, "
            "multiple faces, cropped face, covered face, sunglasses, mask, "
            "worst quality, bad anatomy, watermark, text, "
            "inconsistent appearance, different person"
        )

        results = []
        Path(save_dir).mkdir(parents=True, exist_ok=True)

        for i, angle in enumerate(angle_configs[:n_angles]):
            if on_progress:
                await on_progress(angle["name"], "starting")

            prompt = f"{character_description}, {angle['prompt_suffix']}"

            task_result = await self.create_image_task(
                prompt=prompt,
                negative_prompt=negative,
                model="kling-image",
                aspect_ratio="1:1" if angle["name"] != "halfbody" else "3:4",
                n=1,
            )

            if task_result.get("error"):
                print(f"[Kling] {angle['name']} 角度生成失败: {task_result.get('message')}", flush=True)
                continue

            task_id = task_result.get("task_id")
            if not task_id:
                continue

            if on_progress:
                await on_progress(angle["name"], "waiting")

            result = await self.wait_for_result(task_id, max_wait=180, poll_interval=5)

            if result["status"] != "succeed":
                print(f"[Kling] {angle['name']} 角度任务失败: {result.get('message', '')}", flush=True)
                continue

            images = result.get("images", [])
            if not images:
                continue

            if on_progress:
                await on_progress(angle["name"], "downloading")

            save_path = str(Path(save_dir) / angle["filename"])
            await self.download_image(images[0], save_path)
            results.append(save_path)
            print(f"[Kling] {angle['name']} 角度已保存: {save_path}", flush=True)

        if not results:
            return {"status": "failed", "message": "所有角度生成失败"}

        return {"status": "succeed", "paths": results}

    async def batch_generate_faces(
        self,
        characters: list[dict],
        save_dir: str,
        on_progress=None,
    ) -> dict:
        """
        v12.0: 批量为多个角色生成正脸参考图

        参数:
            characters: 角色列表 [{"name": "...", "description": "..."}, ...]
            save_dir: 保存根目录 (每个角色一个子目录)
            on_progress: 进度回调 callback(char_name: str, status: str)

        返回:
            {"status": "succeed", "results": [{"name": "...", "path": "..."}, ...]}
        """
        results = []
        for char in characters:
            name = char.get("name", "unknown")
            desc = char.get("description", "") or char.get("kling_prompt", "")

            if not desc:
                continue

            if on_progress:
                await on_progress(name, "starting")

            char_dir = str(Path(save_dir) / name)
            result = await self.generate_face_image(
                character_description=desc,
                save_dir=char_dir,
                filename=f"{name}_face.png",
            )

            if result["status"] == "succeed":
                results.append({"name": name, "path": result["path"]})
                if on_progress:
                    await on_progress(name, "done")
            else:
                print(f"[Kling] 角色 {name} 生成失败: {result.get('message')}", flush=True)
                if on_progress:
                    await on_progress(name, "failed")

        return {"status": "succeed", "results": results}
