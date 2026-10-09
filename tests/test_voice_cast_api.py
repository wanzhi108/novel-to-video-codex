"""音色选角在 API 层的契约：人工指定必须锁定，且不被自动分配抢走。

对应 2026-10-09 质量线改动：
- `Character.voice_locked` 默认 False；
- `POST /api/update-character-voice` 人工指定后置 True；
- 自动选角（app/voice_cast.py）不得覆盖已锁定角色，也不得把其音色分给他人。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.models import Character  # noqa: E402


def test_update_character_voice_locks_and_survives_casting(client, app_module):
    created = client.post("/api/create-job")
    assert created.status_code == 200, created.text
    job_id = created.json()["job_id"]

    job = app_module.jobs[job_id]
    job.characters = [
        Character(name="甲", gender="男", voice_id="zh-CN-YunjianNeural"),
        Character(name="乙", gender="男", voice_id="zh-CN-YunjianNeural"),
    ]

    r = client.post(
        "/api/update-character-voice",
        params={"job_id": job_id, "character_name": "甲", "voice_id": "zh-CN-YunyangNeural"},
    )
    assert r.status_code == 200, r.text
    assert job.characters[0].voice_id == "zh-CN-YunyangNeural"
    assert job.characters[0].voice_locked is True, "人工指定后应锁定，避免被自动分配覆盖"

    # 自动选角：不得覆盖甲的锁定音色，也不得把云扬分给乙
    from app.voice_cast import apply_casting

    apply_casting(job.characters)
    assert job.characters[0].voice_id == "zh-CN-YunyangNeural", "锁定音色被覆盖"
    assert job.characters[1].voice_id != "zh-CN-YunyangNeural", "锁定音色被分配给了他人"
    assert job.characters[1].voice_id, "未锁定角色仍应得到音色"


def test_character_voice_candidates_are_fillable(client, app_module):
    """选角结果要能直接喂给前端音色下拉（voice_candidates）。"""
    from app.voice_cast import apply_casting

    chars = [Character(name="甲", gender="女", voice_id="zh-CN-XiaoxiaoNeural")]
    apply_casting(chars)
    assert chars[0].voice_candidates, "候选音色为空，前端无法选择"
    assert "zh-CN-XiaoxiaoNeural" not in chars[0].voice_candidates


def test_main_module_wires_voice_cast():
    """防回退：main.py 的角色分析路径必须接入选角（两处）。"""
    src = (ROOT / "scripts" / "main.py").read_text(encoding="utf-8")
    assert src.count("from app.voice_cast import apply_casting") >= 2, \
        "main.py 应在两条角色分析路径上都接入音色选角"
    assert "char.voice_locked = True" in src, "人工指定音色的接口未设置锁定标记"
