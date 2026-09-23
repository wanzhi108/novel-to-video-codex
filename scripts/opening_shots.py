"""开场片段（药铺/叶玄机）分镜规格。供 T2I 关键帧生成 + Wan5B 渲染共用。"""
from pathlib import Path

KF_DIR = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input")

# 每镜: id, name, kf_prompt(T2I RealVisXL), video_prompt(Wan5B), kf_file
SHOTS = [
    dict(
        id=1,
        name="药铺前堂·叶玄机在柜台",
        kf_file="t2i_s1_kf.png",
        kf_prompt=("interior of an old Chinese herbal medicine shop before dawn, dim moody lighting, "
                   "a young dark-haired man in a worn dark teal cotton jacket working at a long wooden counter, "
                   "rows of dark wooden apothecary jars, a brass scale, bundles of dried herbs, cool blue shadows "
                   "with a faint warm candle glow, cinematic film still, photorealistic, 8k"),
        video_prompt=("a young man in a teal jacket tending dried herbs at a dark wooden counter in a dim old "
                      "Chinese herbal shop, slow subtle hand motion, weighing herbs in a brass scale, quiet "
                      "deliberate movement, cinematic, cool low light with faint warm glow"),
    ),
    dict(
        id=2,
        name="黎明前·叶玄机摸黑起身",
        kf_file="t2i_s2_kf.png",
        kf_prompt=("a dim dark bedroom of an old Chinese house just before dawn, a young man in dark cotton "
                   "clothes sitting up on a simple wooden bed, pitch dark with faint cold blue moonlight through "
                   "a window, moody, cinematic film still, photorealistic, 8k"),
        video_prompt=("the young man slowly rises from the wooden bed, pulls on a dark coat, moves quietly "
                      "in the near-dark, subtle motion, cinematic, cold low light"),
    ),
    dict(
        id=3,
        name="后院·陶罐煎药",
        kf_file="t2i_s3_kf.png",
        kf_prompt=("a rustic courtyard in the dark before dawn, an old clay medicine pot on a low clay stove, "
                   "a small fire glowing beneath, wisps of steam rising, dim, moody, cinematic film still, "
                   "photorealistic, 8k"),
        video_prompt=("the low fire flickers softly, steam rises from the bubbling clay pot, subtle micro "
                      "motion, warm glow in the dark, cinematic"),
    ),
    dict(
        id=4,
        name="柜台·碾薄荷/抓药手部",
        kf_file="t2i_s4_kf.png",
        kf_prompt=("close-up of a young man's hands crushing dried mint leaves on a worn wooden counter, "
                   "brass bowls and a brass scale nearby, dim warm candlelight in an old herbal shop, "
                   "cinematic film still, photorealistic, 8k"),
        video_prompt=("the hands slowly grind dried green mint leaves, a few fragments scatter onto the "
                      "counter, the fingers carefully pick them up, slow deliberate close-up motion, cinematic"),
    ),
    dict(
        id=5,
        name="前堂·掌柜进店对话",
        kf_file="t2i_s5_kf.png",
        kf_prompt=("an old bald Chinese herbal shop owner with half-closed eyes, wearing a faded blue cotton "
                   "jacket, holding an unlit pipe, standing at the counter of a dim old herbal shop, a young "
                   "man nearby, soft dawn light, cinematic film still, photorealistic, 8k"),
        video_prompt=("the old shop owner walks in slowly, glances at the medicine pot, sits down, the young "
                      "man nods and speaks, subtle head and hand motion, quiet conversation, cinematic"),
    ),
    dict(
        id=6,
        name="柜台下沿·神秘划痕",
        kf_file="t2i_s6_kf.png",
        kf_prompt=("extreme close-up of a dark wooden counter edge with a deep scratch mark and a small dark "
                   "dried stain, dim shadows, shallow depth of field, mysterious tense atmosphere, cinematic "
                   "film still, photorealistic, 8k"),
        video_prompt=("the camera slowly pushes in on the deep scratch, a finger traces along the groove, "
                      "subtle micro motion, mysterious tense mood, cinematic"),
    ),
]
