"""
Video Engine — 统一视频生成调度 (v12.0)
支持 7 种视频模式，智能路由，自动降级。
被 main.py 的 _generate_scene_impl 调用，通过依赖注入获取 workflow 和 ComfyUI 客户端。

模式列表:
  1. cloud_t2v  — 云端文生视频（最高质量）
  2. ltx_t2v    — LTX 文生视频（纯文本驱动，无需参考图）
  3. wan21      — Wan2.1 图生视频（高质量，需大显存）
  4. dual_frame — 首尾帧双图 LTX（运动可控）
  5. multi_shot — 多镜头拼接（3段不同构图，叙事推进）
  6. ltx_single — LTX 单帧图生视频（默认本地路径）
  7. ken_burns  — FFmpeg zoompan 推拉摇移（零成本兜底）
  8. parallax   — 三层视差动画（需 SAM 预处理）
"""
import asyncio, subprocess, sys, os, json, copy, random, shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
FFMPEG = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"


# ─── 模式1: 云端文生视频 ──────────────────────────────────

async def _cloud_t2v(scene, scene_dir, job, ctx):
    token = os.environ.get("CLOUD_VIDEO_TOKEN", "")
    if not token: return ""

    from cloud_video import generate as cloud_gen
    prompt = getattr(scene, 'image_prompt', '')[:300] or getattr(scene, 'description', '')[:200]
    if len(prompt) < 20: return ""

    output = str(scene_dir / f"scene_{scene.id:03d}_cloud.mp4")
    ok = await asyncio.get_event_loop().run_in_executor(None, cloud_gen, prompt, output)
    if ok and Path(output).exists() and Path(output).stat().st_size > 10000:
        return output
    return ""


# LTX 22B 图生视频固定使用的 checkpoint（fp8，约29GB，靠 CPU/RAM 卸载在 8.5GB 显存上跑）。
# 注意：LTX 工作流的 CheckpointLoaderSimple / LTXVAudioVAELoader / LTXAVTextEncoderLoader
# 只接受这个 LTX 模型名；绝不能把图生图用的 job.vid_checkpoint（如 RealVisXL）填进去，
# 否则 ComfyUI 报 "Value not in list: ckpt_name" 校验失败 → prompt 被拒 → 路由静默回退 Ken Burns。
LTX_CHECKPOINT = "ltx-2.3-22b-dev-fp8.safetensors"


# ─── 模式2: LTX 文生视频 (T2V) ────────────────────────────

async def _ltx_t2v(scene, scene_dir, job, ctx):
    """LTX 文生视频 — 纯文本驱动，跳过图片生成"""
    comfyui = ctx.get("comfyui")
    lw = ctx.get("load_workflow")
    fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw:
        return ""

    prompt = getattr(scene, 'video_prompt', '') or getattr(scene, 'image_prompt', '')
    if not prompt or len(prompt) < 10:
        return ""

    try:
        t2v_template = lw("txt2vid_ltx") if lw("txt2vid_ltx") else None
        if not t2v_template:
            return ""

        vid_seed = random.randint(0, 2**32 - 1)
        workflow = fw(t2v_template, {
            "POSITIVE_PROMPT": prompt,
            "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or "low quality, blurry, deformed",
            "CHECKPOINT": LTX_CHECKPOINT,
            "TEXT_ENCODER": "gemma_3_12B_it_fpmixed.safetensors",
            "SEED": vid_seed,
            "WIDTH_BASE": 768,
            "HEIGHT_BASE": 1344,
            "LENGTH": 33,
            "FRAME_RATE": 24,
            "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}",
        })
        pid = await comfyui.submit_workflow(workflow)
        res = await comfyui.wait_for_result_ws(pid, job_id=job.id, scene_id=scene.id, timeout=3600)

        finder = ctx.get("find_output_file")
        if not finder:
            return ""
        vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["videos", "gifs", "images"])
        if vf:
            lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
            if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                return lv
    except Exception as e:
        print(f"[VideoEngine] LTX-T2V 失败: {str(e)[:100]}", flush=True)
    return ""


# ─── 模式3: Wan2.1 图生视频 ───────────────────────────────

async def _wan21(scene, scene_dir, job, ctx):
    """Wan2.1 图生视频 — 高质量，需大显存"""
    if not getattr(job, 'use_wan21', False):
        return ""

    comfyui = ctx.get("comfyui")
    lw = ctx.get("load_workflow")
    fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw:
        return ""

    local_img = getattr(scene, 'image_path', None)
    if not local_img or local_img == "__T2V_SKIPPED__":
        return ""
    if not Path(local_img).exists():
        return ""

    vid_base_prompt = ctx.get("vid_base_prompt", "")
    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            uploaded_name = await comfyui.upload_image(local_img)
            vid_seed = random.randint(0, 2**32 - 1)
            wan21_template = lw("img2vid_wan21")
            workflow = fw(wan21_template, {
                "POSITIVE_PROMPT": vid_base_prompt,
                "WAN21_T5_ENCODER": job.wan21_t5_encoder,
                "WAN21_VAE": job.wan21_vae,
                "WAN21_MODEL": job.wan21_model,
                "WAN21_CLIP_VISION": job.wan21_clip_vision,
                "INPUT_IMAGE": uploaded_name,
                "SEED": vid_seed,
                "WIDTH": 720,
                "HEIGHT": 1280,
            })
            pid = await comfyui.submit_workflow(workflow)
            res = await comfyui.wait_for_result_ws(pid, job_id=job.id, scene_id=scene.id, timeout=1800)

            finder = ctx.get("find_output_file")
            if not finder:
                return ""
            vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["gifs", "videos"])
            if vf:
                lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
                if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                    return lv

            if attempt < max_retries:
                await asyncio.sleep((attempt + 1) * 5)
        except Exception as e:
            if attempt < max_retries:
                print(f"[VideoEngine] Wan2.1 重试 {attempt+1}: {str(e)[:80]}", flush=True)
                await asyncio.sleep((attempt + 1) * 5)
            else:
                print(f"[VideoEngine] Wan2.1 失败: {str(e)[:80]}", flush=True)
                break
    return ""


# ─── 模式4: 3层视差 ─────────────────────────────────────

async def _parallax(scene, scene_dir, job, ctx):
    layers = getattr(scene, 'parallax_layers', None)
    if not layers or len(layers) < 3: return ""
    if not all(Path(p).exists() for p in layers[:3]): return ""

    script = PROJECT_DIR / "parallax.py"
    if not script.exists(): return ""

    output = str(scene_dir / f"scene_{scene.id:03d}_parallax.mp4")
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: subprocess.run(
            [sys.executable, str(script)] + layers[:3] + [output, "8"],
            capture_output=True, timeout=60
        )
    )
    if result.returncode == 0 and Path(output).exists(): return output
    return ""


# ─── 模式5: Ken Burns ────────────────────────────────────

async def _ken_burns(scene, scene_dir, job, ctx):
    """Ken Burns 推拉摇移 (FFmpeg zoompan) — 100% 稳定, 无 AI 漂移。"""
    kb_func = ctx.get("ken_burns_func")
    if not kb_func: return ""

    img = getattr(scene, 'image_path', None)
    if not img or not Path(img).exists(): return ""
    if img == "__T2V_SKIPPED__": return ""

    job_id = getattr(job, 'id', '')
    return await kb_func(img, scene, scene_dir, job_id)


# ─── 模式6: 双帧 LTX ────────────────────────────────────

async def _dual_frame(scene, scene_dir, job, ctx):
    if not getattr(job, 'use_dual_frame', False): return ""

    comfyui = ctx.get("comfyui"); lw = ctx.get("load_workflow"); fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw: return ""

    local_img = getattr(scene, 'image_path', None)
    end_img = getattr(scene, 'end_image_path', None)
    if not local_img or not end_img: return ""
    if local_img == "__T2V_SKIPPED__" or not Path(local_img).exists(): return ""

    vid_base_prompt = ctx.get("vid_base_prompt", "")
    scene_frames = ctx.get("scene_frames", 97)

    try:
        start_uploaded = await comfyui.upload_image(local_img)
        end_uploaded = await comfyui.upload_image(end_img)
        vid_seed = random.randint(0, 2**32 - 1)
        dual_template = lw("img2vid_ltx_dual")
        workflow = fw(dual_template, {
            "POSITIVE_PROMPT": vid_base_prompt,
            "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or "low quality, blurry, deformed",
            "CHECKPOINT": LTX_CHECKPOINT,
            "INPUT_IMAGE_START": start_uploaded,
            "INPUT_IMAGE_END": end_uploaded,
            "SEED": vid_seed,
            "WIDTH_BASE": 960,
            "HEIGHT_BASE": 1728,
            # [v2 全面修复·混合短片段] LTX 22B 在 8GB 显存下无法生成长视频
            # （强行匹配配音时长会卡死数小时）。改为短片段(≤33帧≈1.4s)，
            # 再由 combine_audio_video 循环填充到完整配音时长。
            "LENGTH": min(int(scene_frames), 33),
            "FRAME_RATE": 24,
            "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}",
            "LORA_NAME": "ltx-2.3-22b-distilled-lora-384.safetensors",
            "VAE_NAME": LTX_CHECKPOINT,
            "TEXT_ENCODER": "gemma_3_12B_it_fpmixed.safetensors",
            "UPSCALE_MODEL": "ltx-2.3-spatial-upscaler-x2-1.0.safetensors",
        })
        pid = await comfyui.submit_workflow(workflow)
        res = await comfyui.wait_for_result_ws(pid, job_id=job.id, scene_id=scene.id, timeout=1800)

        finder = ctx.get("find_output_file")
        if not finder: return ""
        vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["videos", "gifs"])
        if vf:
            lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
            if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                return lv
    except Exception as e:
        print(f"[VideoEngine] 双帧失败: {str(e)[:80]}", flush=True)
    return ""


# ─── 模式7: 多镜头拼接 ───────────────────────────────────

async def _multi_shot(scene, scene_dir, job, ctx):
    """多镜头 img2vid — 3段不同构图视频拼接，实现叙事推进"""
    if not getattr(job, 'use_multi_shot', False):
        return ""

    comfyui = ctx.get("comfyui"); lw = ctx.get("load_workflow"); fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw: return ""

    local_img = getattr(scene, 'image_path', None)
    if not local_img or local_img == "__T2V_SKIPPED__":
        return ""
    if not Path(local_img).exists():
        return ""

    vid_base_prompt = ctx.get("vid_base_prompt", "")
    scene_frames = ctx.get("scene_frames", 97)
    job_id = getattr(job, 'id', '')
    img2vid_template = lw("img2vid")
    merge_func = ctx.get("merge_videos_func")

    try:
        from PIL import Image
        img = Image.open(local_img)
        w, h = img.size

        shot_configs = [
            {"name": "wide", "crop": (0, 0, w, h),
             "camera": "very slow cinematic push in, wide establishing shot, atmospheric"},
            {"name": "mid", "crop": (int(w*0.08), int(h*0.06), int(w*0.84), int(h*0.88)),
             "camera": "slow cinematic push in, medium shot, elegant composition"},
            {"name": "close", "crop": (int(w*0.12), int(h*0.1), int(w*0.76), int(h*0.8)),
             "camera": "gentle slow push in, intimate detail shot, atmospheric lighting"},
        ]

        shot_videos = []
        for si, sc in enumerate(shot_configs):
            crop_img = img.crop(sc["crop"]).resize((960, 1728), Image.LANCZOS)
            crop_path = str(scene_dir / f"scene_{scene.id:03d}_shot{si+1}.png")
            crop_img.save(crop_path, "PNG")

            uploaded = await comfyui.upload_image(crop_path)
            vid_seed = random.randint(0, 2**32 - 1)
            shot_prompt = f"{vid_base_prompt}, {sc['camera']}"

            workflow = fw(img2vid_template, {
                "POSITIVE_PROMPT": shot_prompt,
                "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or "low quality, blurry, deformed",
                "CHECKPOINT": LTX_CHECKPOINT,
                "TEXT_ENCODER": "gemma_3_12B_it_fpmixed.safetensors",
                "INPUT_IMAGE": uploaded,
                "SEED": vid_seed,
                "WIDTH_BASE": 960,
                "HEIGHT_BASE": 1728,
                "LENGTH": scene_frames,
                "FRAME_RATE": 24,
                "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}_ms{si+1}",
            })
            pid = await comfyui.submit_workflow(workflow)
            res = await comfyui.wait_for_result_ws(pid, job_id=job_id, scene_id=scene.id, timeout=1800)

            finder = ctx.get("find_output_file")
            if not finder: break
            vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["videos", "gifs", "images"])
            if vf:
                lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
                if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                    shot_videos.append(lv)

        if len(shot_videos) >= 2 and merge_func:
            concat_path = str(scene_dir / f"scene_{scene.id:03d}_concat.mp4")
            await merge_func(shot_videos, concat_path)
            if Path(concat_path).exists():
                return concat_path
        elif len(shot_videos) == 1:
            return shot_videos[0]
    except Exception as e:
        print(f"[VideoEngine] 多镜头失败: {str(e)[:80]}", flush=True)
    return ""


# ─── 模式8: 单帧 LTX ────────────────────────────────────

def _build_ltx_camera_directive(scene) -> str:
    """v12.2: 将分镜/运镜(中文)翻译为 LTX 2.3 可理解的英文运镜指令。
    LTX 的 gemma I2V 编码器据提示词中的 camera 描述生成真实运动，
    因此把 shot_size + camera 写进视频正提示词即可驱动真实运镜（无需额外 LoRA）。"""
    shot = (getattr(scene, 'shot_size', '') or '')
    cam = (getattr(scene, 'camera', '') or '')
    parts = []
    # 景别
    if any(k in shot for k in ['特写', 'close']):
        parts.append("close-up shot")
    elif any(k in shot for k in ['近景', 'medium close']):
        parts.append("medium close-up shot")
    elif any(k in shot for k in ['中景', 'medium']):
        parts.append("medium shot")
    elif any(k in shot for k in ['全景', '远景', '广角', 'wide', 'establishing']):
        parts.append("wide establishing shot")
    # 运镜（输出英文，避免 LTX 误解中文；同时匹配中文关键词）
    cl = cam.lower()
    if any(k in cl for k in ['推', 'push', 'dolly in', '前推', 'zoom in']):
        parts.append("the camera slowly pushes in")
    elif any(k in cl for k in ['拉', 'pull', 'dolly out', '拉远', 'zoom out']):
        parts.append("the camera slowly pulls out")
    if any(k in cl for k in ['横移', '跟拍', 'pan', '平移', 'track', '推镜']):
        parts.append("the camera pans horizontally following the subject")
    if any(k in cl for k in ['环绕', 'orbit', 'circle', '绕']):
        parts.append("the camera slowly orbits around the subject")
    if any(k in cl for k in ['摇', 'tilt']):
        parts.append("the camera tilts")
    if any(k in cl for k in ['升', 'crane', 'jib up', '上移']):
        parts.append("the camera rises")
    if any(k in cl for k in ['降', 'jib down', '下移']):
        parts.append("the camera descends")
    # 去重保序
    seen = set(); out = []
    for p in parts:
        if p not in seen:
            seen.add(p); out.append(p)
    return "; ".join(out)


async def _ltx_single(scene, scene_dir, job, ctx):
    comfyui = ctx.get("comfyui"); lw = ctx.get("load_workflow"); fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw: return ""

    img = getattr(scene, 'image_path', None)
    if not img or img == "__T2V_SKIPPED__": return ""
    if not Path(img).exists(): return ""

    vid_base_prompt = ctx.get("vid_base_prompt", "")
    cam_dir = _build_ltx_camera_directive(scene)
    if cam_dir:
        vid_base_prompt = (vid_base_prompt + ". " + cam_dir).strip()
    scene_frames = ctx.get("scene_frames", 97)
    img2vid_template = lw("img2vid")

    try:
        uploaded_name = await comfyui.upload_image(img)
        vid_seed = random.randint(0, 2**32 - 1)
        workflow = fw(img2vid_template, {
            "POSITIVE_PROMPT": vid_base_prompt,
            "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or (
                "low quality, worst quality, blurry, deformed, watermark, text, "
                "extra digits, fewer digits, cropped, ugly, duplicate, "
                "morbid, mutilated, out of frame, mutation, deformed, "
                "bad anatomy, bad proportions, missing arms, missing legs, "
                "extra limbs, fused fingers, too many fingers, "
                "long neck, username, watermark, signature"
            ),
            "CHECKPOINT": LTX_CHECKPOINT,
            "TEXT_ENCODER": "gemma_3_12B_it_fpmixed.safetensors",
            "INPUT_IMAGE": uploaded_name,
            "SEED": vid_seed,
            "WIDTH_BASE": 960,
            "HEIGHT_BASE": 1728,
            # [v2 全面修复·混合短片段] LTX 22B 在 8GB 显存下无法生成长视频
            # （强行匹配配音时长会卡死数小时）。改为短片段(≤33帧≈1.4s)，
            # 再由 combine_audio_video 循环填充到完整配音时长。
            "LENGTH": min(int(scene_frames), 33),
            "FRAME_RATE": 24,
            "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}",
        })
        pid = await comfyui.submit_workflow(workflow)
        res = await comfyui.wait_for_result_ws(pid, job_id=job.id, scene_id=scene.id, timeout=3600)

        finder = ctx.get("find_output_file")
        if not finder: return ""
        vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["videos", "gifs", "images"])
        if vf:
            lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
            if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                return lv
    except Exception as e:
        print(f"[VideoEngine] LTX 单帧失败: {str(e)[:80]}", flush=True)
    return ""


# ─── 调度器 ─────────────────────────────────────────────

# 所有可用模式
VIDEO_MODES = {
    "cloud_t2v":  _cloud_t2v,
    "ltx_t2v":    _ltx_t2v,
    "wan21":      _wan21,
    "dual_frame": _dual_frame,
    "multi_shot": _multi_shot,
    "ltx_single": _ltx_single,
    "parallax":   _parallax,
    "ken_burns":  _ken_burns,
}


def _classify_scene_video_mode(scene, job=None) -> str:
    """智能路由：默认 LTX 为主引擎；Ken Burns 仅用于无人物的大场景推拉/定场空镜 + 最终兜底。

    路由规则（v12.2 更新：用户要求 LTX 22B 为主，KB 只负责大场景推拉）：
      - 无人物 / 纯环境 / 全景·远景·广角等大场景 → Ken Burns（稳定、零成本推拉）
      - 其余（有角色、对白、动作、情绪）→ LTX（真视频运动）

    Returns:
        'ltx' | 'ken_burns' | 'dual_frame' | 'cloud'
    """
    desc = (getattr(scene, 'description', '') or '').lower()
    camera = (getattr(scene, 'camera', '') or '').lower()
    shot_size = (getattr(scene, 'shot_size', '') or '').lower()
    chars = getattr(scene, 'characters', '') or ''
    video_prompt = getattr(scene, 'video_prompt', '') or ''

    # 无人物场景标记
    no_char_markers = ["无", "无角色", "本镜未出场", "未出场", "环境开场"]
    is_env = any(m in str(chars) for m in no_char_markers) or not str(chars).strip()
    # 大场景推拉（定场空镜）
    big_shot = any(k in shot_size for k in ['全景', '远景', '广角', '大场景',
                                            'establishing', 'wide', 'panorama'])

    # 无人物 / 纯环境 / 大场景 → Ken Burns 推拉
    if is_env or big_shot:
        return 'ken_burns'

    # 其余默认 LTX（有角色、对白、动作、情绪都走真视频）
    return 'ltx'


def _is_static_video(path: str) -> bool:
    """检测视频是否静态（帧数 < 24）"""
    try:
        pr = subprocess.run(
            [FFPROBE, '-v', 'quiet', '-count_frames', '-select_streams', 'v:0',
             '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=15
        )
        nframes = int(pr.stdout.strip() or 0)
        return nframes < 24
    except Exception:
        return False


async def dispatch(scene, scene_dir, ctx: dict) -> str:
    """统一视频生成调度入口。

    ctx 需要包含:
        - comfyui: ComfyUIClient 实例
        - job: JobState 实例
        - load_workflow: 加载工作流模板的函数
        - fill_workflow: 填充工作流参数的函数
        - ken_burns_func: Ken Burns 生成函数
        - find_output_file: 查找输出文件的函数
        - vid_base_prompt: 视频提示词
        - scene_frames: 视频帧数
        - merge_videos_func: 视频合并函数（多镜头模式用）

    返回视频文件路径，失败返回空字符串。
    """
    job = ctx.get("job")
    mode = getattr(job, 'video_mode', 'local') if job else 'local'
    local_img = getattr(scene, 'image_path', None)
    intensity = getattr(scene, 'emotional_intensity', 5)
    camera = (getattr(scene, 'camera', '') or '').lower()
    desc = (getattr(scene, 'description', '') or '').lower()
    action_kws = ['跑', '冲', '追', '打', '摔', '爆炸', '撞', '飞',
                  'jump', 'run', 'fight', 'chase', 'explosion', 'attack']
    is_action = any(kw in desc or kw in camera for kw in action_kws)

    # ── T2V 模式：纯文生视频，跳过图片 ──
    if mode == "ltx_t2v":
        print(f"[VideoEngine] 场景 {scene.id}: LTX-T2V 文生视频模式", flush=True)
        r = await _ltx_t2v(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "ltx_t2v"
            return r
        # T2V 失败，降级到 Ken Burns（如果有图片）
        if local_img and local_img != "__T2V_SKIPPED__" and Path(local_img).exists():
            r = await _ken_burns(scene, scene_dir, job, ctx)
            if r:
                scene.video_mode_used = "ken_burns"
                return r
        return ""

    # ── Cloud T2V 模式 ──
    if mode == "cloud_t2v":
        r = await _cloud_t2v(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "cloud_t2v"
            return r
        # 云端失败，继续走本地路径

    # ── v12.0: 智能路由 — 根据场景特征选择主用引擎 ──
    primary = _classify_scene_video_mode(scene, job)
    print(f"[VideoEngine] 场景 {scene.id}: 路由={primary} (mood={getattr(scene, 'mood', '')} "
          f"intensity={intensity} camera={camera[:15]})", flush=True)

    # 构建尝试顺序
    if primary == 'ltx':
        ordered = ['wan21', 'ltx_single', 'ken_burns', 'dual_frame', 'parallax']
    elif primary == 'dual_frame' and job and getattr(job, 'use_dual_frame', False):
        ordered = ['dual_frame', 'ltx_single', 'ken_burns']
    else:
        # primary='ken_burns' 或默认 — 先 Ken Burns（快、稳），失败回退 LTX
        ordered = ['ken_burns', 'ltx_single', 'parallax']

    # 插入 multi_shot 到 LTX 之前（如果启用）
    if job and getattr(job, 'use_multi_shot', False):
        if 'ltx_single' in ordered:
            idx = ordered.index('ltx_single')
            ordered.insert(idx, 'multi_shot')

    for name in ordered:
        func = VIDEO_MODES.get(name)
        if not func:
            continue
        # 跳过未启用的模式
        if name == 'dual_frame' and not (job and getattr(job, 'use_dual_frame', False)):
            continue
        if name == 'wan21' and not (job and getattr(job, 'use_wan21', False)):
            continue
        if name == 'multi_shot' and not (job and getattr(job, 'use_multi_shot', False)):
            continue
        if name == 'ken_burns' and not (job and getattr(job, 'use_ken_burns', False)):
            # Ken Burns 仅在启用时使用，或作为最后兜底
            if name != ordered[-1]:
                continue

        try:
            r = await func(scene, scene_dir, job, ctx)
            if r and Path(r).exists():
                # 验证视频不是静态（>=24 帧），但 Ken Burns 除外
                if name == 'ltx_single' and _is_static_video(r):
                    print(f"[VideoEngine] 场景 {scene.id}: LTX 输出静态，跳过回退", flush=True)
                    try:
                        Path(r).unlink()
                    except Exception:
                        pass
                    continue
                scene.video_mode_used = name
                print(f"[VideoEngine] 场景 {scene.id}: 使用 {name} → {r}", flush=True)
                return r
        except Exception as e:
            print(f"[VideoEngine] {name} 失败: {str(e)[:80]}", flush=True)
            continue

    # ── 最终兜底：Ken Burns（即使未启用，也尝试） ──
    if local_img and local_img != "__T2V_SKIPPED__" and Path(local_img).exists():
        kb_func = ctx.get("ken_burns_func")
        if kb_func and not is_action and intensity < 8:
            try:
                r = await _ken_burns(scene, scene_dir, job, ctx)
                if r and Path(r).exists():
                    scene.video_mode_used = "ken_burns"
                    print(f"[VideoEngine] 场景 {scene.id}: 最终兜底 Ken Burns", flush=True)
                    return r
            except Exception:
                pass

    return ""
