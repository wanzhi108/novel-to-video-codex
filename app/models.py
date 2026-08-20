"""
数据模型 - Pydantic models
"""
from pydantic import BaseModel, field_validator
from typing import Optional
from pathlib import Path


class Character(BaseModel):
    """角色信息模型"""
    name: str = ""
    gender: str = ""          # 男/女/未知
    age_range: str = ""       # 儿童/少年/青年/中年/老年
    personality: str = ""
    role_type: str = ""       # 主角/配角/反派/旁白/路人
    voice_id: str = ""        # Edge-TTS 声音 ID
    voice_name: str = ""      # 声音中文名
    cosyvoice_voice: str = "" # CosyVoice2 speaker 名（v11 新增）
    speaking_style: str = ""

    # v12.0: 候选音色列表（每个角色绑定 1-3 个候选音色，支持试听选择）
    voice_candidates: list[str] = []  # Edge-TTS voice_id 列表

    # v5.3: 外貌/身体/着装特征 (用于可灵AI生成角色正脸)
    appearance: str = ""      # 外貌特征: 发型、发色、脸型、眼睛颜色、五官特点
    body_type: str = ""      # 身体特征: 身高、体型、姿态特点
    clothing: str = ""       # 着装特征: 常穿的衣服款式、颜色、配饰
    kling_prompt: str = ""  # 可直接用于可灵AI的英文prompt (正面清晰角色脸)

    # v12.0: 角色素材库目录（素材库自动构建时写入，定义为字段以避免 Pydantic setattr 报 "object has no field"）
    material_library_path: str = ""


class Scene(BaseModel):
    """场景模型"""
    id: int
    subtitle_text: str = ""
    subtitle_display: str = ""
    title: str = ""
    description: str = ""
    characters: str = ""
    speaking_characters: list[str] = []
    setting: str = ""
    mood: str = ""
    camera: str = ""
    shot_size: str = ""                  # 景别: 特写/近景/中景/全景/远景 — 用于 LTX 运镜指令与节奏
    duration: str = "5s"
    image_prompt: str = ""
    video_prompt: str = ""
    negative_prompt: str = ""
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    final_video_path: Optional[str] = None
    audio_path: Optional[str] = None
    audio_duration: float = 0.0
    subtitle_timings: list[dict] = []
    status: str = "pending"
    error_msg: str = ""
    comfyui_progress: float = 0.0

    # v5.0 好莱坞级分镜字段
    emotional_intensity: int = 5          # 情绪强度 1-10，来自故事结构预分析
    visual_motif_note: str = ""          # 本镜如何体现视觉母题
    continuity_note: str = ""             # 与前后镜头的空间/时间/情绪衔接
    story_act: str = ""                 # 本镜所在的故事幕次：act1 / act2 / act3
    story_position: str = ""             # 本镜在故事中的位置描述
    storytelling_rhythm: str = ""        # 节奏类型：hook/conflict/reversal/cliffhanger/emotional_peak/info_drop/suspense

    # v7.0 Seedream 蒸馏: VMix 美学标签
    vmix_tags: dict = {}                 # {"palette": "...", "lighting": "...", "composition": "..."}

    # v7.2 视频引擎扩展字段
    video_mode_used: str = ""            # 实际使用的视频模式: cloud_t2v/ken_burns/parallax/dual_frame/ltx_single
    parallax_layers: list[str] = []      # 三层视差图层路径: [bg, char, fg]
    end_image_path: Optional[str] = None # 双帧模式尾帧图片路径

    @field_validator('emotional_intensity', mode='before')
    @classmethod
    def coerce_emotional_intensity_to_int(cls, v: object) -> int:
        """安全转换为 int，防御 LLM 返回浮点数（如 9.5 → 9）"""
        try:
            return int(float(v))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return 5


class JobState(BaseModel):
    """任务状态模型"""
    id: str
    novel_text: str = ""
    novel_title: str = ""
    deepseek_key: str = ""
    scenes: list[Scene] = []
    characters: list[Character] = []
    current_step: str = "upload"
    progress: dict = {}
    error: str = ""
    cancel_flag: bool = False       # 取消生成标志
    story_structure: dict = {}      # v5.0 好莱坞级：故事结构预分析结果
    
    # 模型选择（默认 SDXL，画质最优）
    img_checkpoint: str = "animagine-xl-4.0.safetensors"
    vid_checkpoint: str = "ltx-2.3-22b-dev-fp8.safetensors"
    
    # Level 1: Hires.fix
    use_hires_fix: bool = True
    
    # Level 2: IP-Adapter 角色一致性 (v8.7: SDXL模型就位)
    use_ipadapter: bool = False
    ipadapter_model: str = "ip-adapter-plus-face_sdxl_vit-h.safetensors"
    ipadapter_reference_image: str = ""
    clip_vision_model: str = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"

    # Level 2b: PuLID 角色一致性 (SDXL)
    use_pulid: bool = False
    pulid_model: str = "ip-adapter_pulid_sdxl_fp16.safetensors"
    pulid_reference_image: str = ""
    kling_api_key: str = ""               # 可灵API Key
    kling_face_description: str = ""      # 可灵角色描述
    
    # Level 3: Wan2.1 图生视频
    use_wan21: bool = False
    wan21_model: str = "WanVideo\\Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors"
    wan21_t5_encoder: str = "umt5-xxl-enc-bf16.safetensors"
    wan21_vae: str = "wanvideo\\Wan2_1_VAE_bf16.safetensors"
    wan21_clip_vision: str = "clip_vision_h.safetensors"
    
    # Level 3b: Ken Burns 动画模式 (v7.0/v8.0 降级为最后备选)
    use_ken_burns: bool = False  # FFmpeg zoompan 推拉摇移, 仅在所有真视频失败时兜底
    
    # Level 3c: 首尾帧双图视频 (v7.0)
    use_dual_frame: bool = False  # LTX 双帧 Inplace + CropGuides

    # Level 4: TTS + 字幕
    tts_enabled: bool = True
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_rate: str = "+5%"
    
    # Level 4b: 视频模式 (v7.2)
    video_mode: str = "local"  # "local" | "cloud_t2v" | "ltx_t2v" | "ltx_t2v"
    tts_volume: str = "+10%"
    narrator_voice: str = "zh-CN-YunxiNeural"
    smart_dubbing: bool = True
    use_ass_subtitles: bool = True
    
    # Level 5: 后期处理
    use_color_grading: bool = True
    use_fade_transition: bool = True
    use_manga_fx: bool = True  # v7.2: 伪声字特效 + 角色标签 + 底部字幕
    use_multi_shot: bool = False  # v8.3: 多镜头img2vid (3镜头拼接, 实现叙事推进)
    
    # QA 自测试
    qa_enabled: bool = True
    qa_results: list[dict] = []
    qa_passed: bool = False
    
    # 风格预设
    style: str = "cinematic"

    # 题材偏好（红果五类流量倾斜题材）
    subject_preference: str = ""  # 言情/古风玄幻/都市轻悬疑/现代甜宠/奇幻冒险

    # v6.2: 角色与环境预分析（在分镜生成前提取，确保跨镜一致性）
    character_analysis: Optional[dict] = None   # {characters: [{name, role, gender, age_appearance, physical_description, face_detail, hair_style, clothing_evolution, personality_traits, typical_expression, special_marks, relationships, importance_level}]}
    environment_analysis: Optional[dict] = None  # {environments: [{name, location_type, description, time_period, lighting, color_scheme, atmosphere, key_props, scale}]}

    # 输出路径
    merged_video_path: str = ""  # 最终合成视频路径
    cover_path: str = ""  # v6.0: 封面图路径


class GenerateRequest(BaseModel):
    """生成请求"""
    novel_text: str
    novel_title: str = ""
    deepseek_key: str = ""
    # 模型选择（默认 SDXL，画质最优）
    img_checkpoint: str = "animagine-xl-4.0.safetensors"
    vid_checkpoint: str = "ltx-2.3-22b-dev-fp8.safetensors"
    use_hires_fix: bool = True
    use_ipadapter: bool = False
    use_pulid: bool = False
    pulid_reference_image: str = ""
    kling_api_key: str = ""
    kling_face_description: str = ""
    use_wan21: bool = False
    use_color_grading: bool = True
    use_fade_transition: bool = True
    style: str = "cinematic"
    # v7.2 新增
    use_ken_burns: bool = False
    use_dual_frame: bool = False
    use_manga_fx: bool = True
    use_multi_shot: bool = False  # v8.3: 多镜头 img2vid
    video_mode: str = "local"  # "local" | "cloud_t2v" | "ltx_t2v" | "ltx_t2v"
    tts_enabled: bool = True
    smart_dubbing: bool = True
