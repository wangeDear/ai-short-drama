# Project023 AI 短剧生产线

> 优云智算 5090 + ComfyUI | 从剧本到成片的自动化短剧生产管线
> 当前生产版本：**v9**（H3 vlog 竖屏管线，2026-08-17 验收通过）

## 文档索引

| 文档 | 用途 |
|---|---|
| `docs/01_当前方案总览.md` | ⭐ 一页看懂现状 |
| `docs/02_流水线定稿_v2.md` | ⭐ 生产规范（六段式模板/工程参数/SOP）|
| `docs/05_行业主流方案调研_2026-08.md` | 行业背景 |
| `docs/06_H3官方提示词规范.md` | 六段式原始规范出处 |
| `docs/09_AI短剧生成审核工作台_需求文档.md` | 生成审核工作台需求 |
| `docs/工作流优化日志.md` | v1-v9 演进史与全部踩坑（只增不删）|

## 生成审核工作台

`workbench/` 是分阶段创作与审核工作台 v0.3（FastAPI + SQLite + HTMX，`python -m workbench` → http://127.0.0.1:8770）：
支持创意文本 → 剧本 → 生产设定 → 结构化提示词 → 图片/视频生成 → 成片的全链路（A~D 人工卡点，
内置离线 Mock LLM 与 Mock 生成节点），详见 `workbench/README.md`。旧的 `studio/` 单项目审核台保留作对照。

## 已交付作品

| 作品 | 版本 | 位置（outputs/） |
|---|---|---|
| **森林求生·取火篇**（3min 竖屏 vlog）| ⭐ 最终验收版 | `forest_fire/取火篇_vlog竖屏_final.mp4` |
| 财神爷被裁员（5min 写实 24 镜）| H3 版（对照资产）| `csr_final.mp4` + 24 分镜 |
| 财神 v3 第一幕（连贯性验证集）| 历史版本 | `c3_act1_final.mp4` + 8 分镜 |
| 月亮邮递员（15s 单段试验）| Project022 | 见 Project022/outputs |

> LTX 系过程产物（704p 版/黑屏版/demo/分镜/关键帧）已于 2026-08-17 清理，仅存最终验收版。

## 核心资产

- **服务器脚本**（`/root/story_test/`）：`fire_vlog_full.py`（全量管线）、`h3vlog_demo.py`（demo 流程）、历史各版
- **参考图**（服务器 input/）：fr_hero/fr_forest/fr_storm + fd_selfie/fd_overhead/fd_storm
- **踩坑总表**：工作流优化日志各版"踩坑记录"节

## 下一步

新剧集按 `docs/02_流水线定稿_v2.md` §六 SOP 执行（管线零改动）。
