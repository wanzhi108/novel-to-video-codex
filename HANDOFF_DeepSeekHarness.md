# DeepSeek Harness 交接清单

本文件用于把本机 `novel-to-video-codex` 仓库及 `overtime-cat` 项目完整交给 DeepSeek Harness 接手。

## 交接对象

- 仓库：`D:\novel-to-video-codex`
- 当前成片项目：`D:\novel-to-video-codex\OpenMontage\projects\overtime-cat`
- 成片：`D:\novel-to-video-codex\OpenMontage\projects\overtime-cat\renders\final.mp4`
- 成片规格：`1920x1080`、`30fps`、`30.06s`、H.264 + AAC、约 8.2 MB
- 成片状态：compose 已完成，`final_review.json` 为 `pass`

## 项目状态

- 技术栈：LuminaForge 桌面应用 + story2 管线 + ComfyUI LTX/Wan + Remotion 合成
- LTX 短片段使用 freeze-frame 修复，涉及 `CinematicRenderer.tsx`、`types.ts`、`video_compose.py`
- 音乐：`assets\music\overtime_cat_bgm.mp3`，Pixabay License
- 自审：`artifacts\final_review.json`，状态 `pass`
- 已知警告：
  - motion ratio 67%，低于 `motion_led` 70% 阈值；原因是 6 个 cut 中 4 个为真实 LTX 动镜头，另 2 个为标题卡，属于计数口径问题
  - transcript comparison 未运行，因为该片没有旁白

## Checkpoint 与关键文件

- 项目根目录：`D:\novel-to-video-codex\OpenMontage\projects\overtime-cat`
- Checkpoint：`checkpoint_research.json`、`checkpoint_proposal.json`、`checkpoint_script.json`、`checkpoint_scene_plan.json`、`checkpoint_assets.json`、`checkpoint_edit.json`、`checkpoint_compose.json`
- 渲染报告：`artifacts\render_report.json`
- 最终自审：`artifacts\final_review.json`
- 决策日志：`decision_log.json`
- 事件记录：`events.jsonl`

## Git 状态

- 最近提交：`629be1a`、`fe83318`、`2bc588f`、`cce0019`、`73641d6`
- 仓库没有配置 remote
- 工作区很脏：`OpenMontage/` 整个目录未跟踪，另有大量已修改文件和未跟踪文件
- 交接前不要执行 `git reset` / `git checkout`，不要丢弃用户改动
- 用户改动集中在 `app/`、`comfyui/`、`scripts/`、`story2/`、`web/` 等目录

## DeepSeek Harness 交接信息

- dsh Web：`http://127.0.0.1:<port>`
- 已注册工作区：`<项目根目录>`
- 工作区 ID / 导入会话 ID / 源会话文件路径：**已按安全要求移除（不公开本机标识）**

## 如何继续

1. 打开 dsh Web（本机地址），进入项目工作区。
2. 新建会话后用 `/resume-codex <会话ID>` 续聊（会话 ID 已按安全要求移除）。
3. 若需要重新运行 OpenMontage，遵循 `OpenMontage\AGENT_GUIDE.md` 的管线规则，不要绕过 pipeline 直接调用工具。
4. 如需处理 dirty worktree，先与用户确认哪些改动要保留，再决定提交策略。

## 注意事项

- 导入会话的 cwd 曾导致自动挂载失败；交接时已删除导入插件自动创建的空源目录工作区。
- 在 dsh 中继续时，建议显式打开项目根目录工作区，或使用 `/attach-workspaces` 绑定。
- dsh 的凭据文件路径已按安全要求移除；本文件不包含任何密钥。
- 本项目可继续改进的方向：角色/场景/物品一致性、长视频分镜稳定性、有限显存下的 LTX 模式、分辨率提升、参考图闭环。
