"""
v12.0: 环境与道具图生成模块

功能:
1. 为每个独立场景生成纯环境参考图（无人物）
2. 关键道具独立生成特写图
3. 同地点环境图缓存复用
4. 集成可灵 AI / DeepSeek API

使用方式:
    from environment_generator import EnvironmentGenerator
    gen = EnvironmentGenerator(kling_api_key="...")
    env_img = await gen.get_or_create_environment_image(scene, job, save_dir)
    prop_img = await gen.generate_prop_closeup("ancient sword", save_dir)
"""
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

# 延迟导入，避免循环依赖
def _get_deepseek_key():
    try:
        from app.config import DEEPSEEK_API_KEY
        return DEEPSEEK_API_KEY
    except ImportError:
        return os.environ.get("DEEPSEEK_API_KEY", "")


class EnvironmentGenerator:
    """环境与道具图生成器"""

    def __init__(self, kling_api_key: str = "", deepseek_key: str = ""):
        self.kling_api_key = kling_api_key
        self.deepseek_key = deepseek_key or _get_deepseek_key()
        self._cache: dict[str, str] = {}  # env_name -> image_path

    def _env_cache_key(self, env_name: str, env_desc: str) -> str:
        """生成环境缓存键 — 同名称+同描述视为同一环境"""
        raw = f"{env_name}_{env_desc}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    async def _rewrite_env_prompt(self, env_info: dict) -> str:
        """用 DeepSeek 将中文环境描述转为英文绘图 prompt"""
        if not self.deepseek_key:
            # 无 DeepSeek，简单拼接
            desc = env_info.get("description", "")
            atmosphere = env_info.get("atmosphere", "")
            lighting = env_info.get("lighting", "")
            return f"{desc}, {atmosphere}, {lighting}, no people, empty scene, environmental shot"

        desc = env_info.get("description", "")
        atmosphere = env_info.get("atmosphere", "")
        lighting = env_info.get("lighting", "")
        color_scheme = env_info.get("color_scheme", "")
        scale = env_info.get("scale", "")
        time_period = env_info.get("time_period", "")

        system_msg = """你是专业场景概念设计师。将中文环境描述转为高质量英文绘图prompt。
要求:
- 纯环境图，无人物 (no people, empty scene)
- 包含光线、色调、空间感、氛围
- 电影级画面质量
只输出prompt文本，不加解释。"""

        user_msg = f"""环境名称: {env_info.get('name', '')}
描述: {desc}
氛围: {atmosphere}
光线: {lighting}
色调: {color_scheme}
空间尺度: {scale}
时间段: {time_period}"""

        try:
            from main import call_deepseek
            result = await call_deepseek(
                self.deepseek_key, system_msg, user_msg,
                max_tokens=256, temperature=0.4
            )
            return result.strip().strip('"').strip("'").strip()
        except Exception:
            # 回退到简单拼接
            return f"{desc}, {atmosphere}, {lighting}, no people, empty scene, environmental shot, cinematic"

    async def _rewrite_prop_prompt(self, prop_name: str, prop_context: str = "") -> str:
        """用 DeepSeek 将中文道具描述转为英文特写 prompt"""
        if not self.deepseek_key:
            return f"close-up shot of {prop_name}, product photography, high detail, centered composition, clean background, 8k quality"

        system_msg = """你是专业产品摄影师。将道具描述转为高质量英文特写绘图prompt。
要求:
- 物品特写 (close-up shot, centered composition)
- 干净背景 (clean neutral background)
- 高细节、专业光影
- 1:1 正方形构图
只输出prompt文本，不加解释。"""

        user_msg = f"道具名称: {prop_name}\n相关背景: {prop_context}"

        try:
            from main import call_deepseek
            result = await call_deepseek(
                self.deepseek_key, system_msg, user_msg,
                max_tokens=128, temperature=0.3
            )
            return result.strip().strip('"').strip("'").strip()
        except Exception:
            return f"close-up shot of {prop_name}, product photography, high detail, centered composition, clean background, 8k quality"

    async def _generate_with_kling(self, prompt: str, save_path: str, aspect_ratio: str = "9:16") -> bool:
        """调用可灵 AI 生成图片"""
        if not self.kling_api_key:
            return False

        try:
            from kling_client import KlingImageClient
            kling = KlingImageClient(api_key=self.kling_api_key)

            task_result = await kling.create_image_task(
                prompt=prompt,
                negative_prompt="people, person, character, face, text, watermark, low quality, blurry",
                model="kling-image",
                aspect_ratio=aspect_ratio,
                n=1,
            )

            if task_result.get("error"):
                return False

            task_id = task_result.get("task_id")
            if not task_id:
                return False

            result = await kling.wait_for_result(task_id, max_wait=180, poll_interval=5)

            if result["status"] != "succeed":
                return False

            images = result.get("images", [])
            if not images:
                return False

            await kling.download_image(images[0], save_path)
            return True
        except Exception as e:
            print(f"[EnvGen] 可灵生成失败: {str(e)[:100]}", flush=True)
            return False

    async def _generate_with_comfyui(self, prompt: str, save_path: str, job=None) -> bool:
        """回退方案: 使用 ComfyUI txt2img 生成环境图"""
        try:
            from main import comfyui, load_workflow, fill_workflow, OUTPUT_DIR

            txt2img_template = load_workflow("txt2img")
            seed = abs(hash(prompt)) % (2**31)

            checkpoint = getattr(job, 'img_checkpoint', 'animagine-xl-4.0.safetensors') if job else 'animagine-xl-4.0.safetensors'

            workflow = fill_workflow(txt2img_template, {
                "POSITIVE_PROMPT": f"masterpiece, best quality, {prompt}",
                "NEGATIVE_PROMPT": "(worst quality:1.5), (low quality:1.5), blurry, people, person, character, face, text, watermark",
                "SEED": seed,
                "WIDTH": 1080,
                "HEIGHT": 1920,
                "CHECKPOINT": checkpoint,
            })

            prompt_id = await comfyui.submit_workflow(workflow)
            result = await comfyui.wait_for_result_ws(prompt_id, timeout=300)

            outputs = result.get("outputs", {})
            for node_id, node_out in outputs.items():
                if "images" in node_out:
                    img_info = node_out["images"][0]
                    local_path = await comfyui.download_output(
                        img_info["filename"],
                        img_info.get("subfolder", ""),
                        save_dir=Path(save_path).parent
                    )
                    if local_path and Path(local_path).exists():
                        # 重命名
                        Path(local_path).rename(save_path)
                        return True
        except Exception as e:
            print(f"[EnvGen] ComfyUI 生成失败: {str(e)[:100]}", flush=True)
        return False

    async def get_or_create_environment_image(
        self,
        env_info: dict,
        save_dir: str,
        job=None,
    ) -> Optional[str]:
        """
        获取或创建环境参考图 — 同环境只生成一次

        参数:
            env_info: 环境信息 {"name": "...", "description": "...", "atmosphere": "...", ...}
            save_dir: 保存目录
            job: 任务对象（用于获取 ComfyUI 配置）

        返回:
            图片路径，失败返回 None
        """
        env_name = env_info.get("name", "unknown_env")
        env_desc = env_info.get("description", "")

        # 检查缓存
        cache_key = self._env_cache_key(env_name, env_desc)
        if cache_key in self._cache:
            cached_path = self._cache[cache_key]
            if Path(cached_path).exists():
                print(f"[EnvGen] 环境图缓存命中: {env_name}", flush=True)
                return cached_path

        # 生成英文 prompt
        env_prompt = await self._rewrite_env_prompt(env_info)
        if not env_prompt or len(env_prompt) < 20:
            env_prompt = f"{env_desc}, no people, empty scene, environmental shot, cinematic lighting, 8k"

        # 保存路径
        env_dir = Path(save_dir) / "environments"
        env_dir.mkdir(parents=True, exist_ok=True)
        safe_name = env_name.replace(" ", "_").replace("/", "_")[:30]
        save_path = str(env_dir / f"{safe_name}.png")

        # 如果已存在，直接返回
        if Path(save_path).exists():
            self._cache[cache_key] = save_path
            return save_path

        print(f"[EnvGen] 生成环境图: {env_name} → {env_prompt[:80]}...", flush=True)

        # 方案 A: 可灵 AI
        success = await self._generate_with_kling(env_prompt, save_path, aspect_ratio="9:16")

        # 方案 B: ComfyUI 回退
        if not success:
            print(f"[EnvGen] 可灵失败，回退 ComfyUI", flush=True)
            success = await self._generate_with_comfyui(env_prompt, save_path, job=job)

        if success:
            self._cache[cache_key] = save_path
            print(f"[EnvGen] 环境图已保存: {save_path}", flush=True)
            return save_path

        return None

    async def generate_prop_closeup(
        self,
        prop_name: str,
        save_dir: str,
        prop_context: str = "",
        job=None,
    ) -> Optional[str]:
        """
        生成道具特写图

        参数:
            prop_name: 道具名称 (如 "上古宝剑")
            save_dir: 保存目录
            prop_context: 相关背景描述
            job: 任务对象

        返回:
            图片路径，失败返回 None
        """
        prop_prompt = await self._rewrite_prop_prompt(prop_name, prop_context)

        prop_dir = Path(save_dir) / "props"
        prop_dir.mkdir(parents=True, exist_ok=True)
        safe_name = prop_name.replace(" ", "_").replace("/", "_")[:30]
        save_path = str(prop_dir / f"{safe_name}.png")

        if Path(save_path).exists():
            return save_path

        print(f"[EnvGen] 生成道具特写: {prop_name} → {prop_prompt[:80]}...", flush=True)

        # 方案 A: 可灵 AI (1:1 构图)
        success = await self._generate_with_kling(prop_prompt, save_path, aspect_ratio="1:1")

        # 方案 B: ComfyUI 回退
        if not success:
            success = await self._generate_with_comfyui(prop_prompt, save_path, job=job)

        if success:
            print(f"[EnvGen] 道具特写已保存: {save_path}", flush=True)
            return save_path

        return None

    async def pre_generate_environments(
        self,
        job,
        save_dir: str,
        on_progress=None,
    ) -> dict:
        """
        在分镜生成前预生成所有环境图和关键道具图

        参数:
            job: JobState 对象
            save_dir: 保存根目录
            on_progress: 进度回调 callback(name: str, status: str)

        返回:
            {"environments": {env_name: path}, "props": {prop_name: path}}
        """
        results = {"environments": {}, "props": {}}

        if not job.environment_analysis or not isinstance(job.environment_analysis.get("environments"), list):
            return results

        envs = job.environment_analysis["environments"]
        total = len(envs)

        for i, env in enumerate(envs):
            env_name = env.get("name", f"env_{i}")
            if on_progress:
                await on_progress(env_name, "starting")

            env_path = await self.get_or_create_environment_image(env, save_dir, job=job)
            if env_path:
                results["environments"][env_name] = env_path
                if on_progress:
                    await on_progress(env_name, "done")
            else:
                if on_progress:
                    await on_progress(env_name, "failed")

            # 为每个环境的关键道具生成特写
            key_props = env.get("key_props", "")
            if key_props and isinstance(key_props, str):
                # 解析道具列表（逗号或顿号分隔）
                props = [p.strip() for p in key_props.replace("、", ",").split(",") if p.strip()]
                for prop in props[:3]:  # 每个环境最多 3 个道具
                    if on_progress:
                        await on_progress(f"prop:{prop}", "starting")
                    prop_path = await self.generate_prop_closeup(prop, save_dir, prop_context=env_name, job=job)
                    if prop_path:
                        results["props"][prop] = prop_path
                        if on_progress:
                            await on_progress(f"prop:{prop}", "done")
                    else:
                        if on_progress:
                            await on_progress(f"prop:{prop}", "failed")

        print(f"[EnvGen] 预生成完成: {len(results['environments'])} 个环境图, {len(results['props'])} 个道具图", flush=True)
        return results
