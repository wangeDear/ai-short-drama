# AI 短剧分阶段生成与审核工作台

需求文档：`docs/09_AI短剧生成审核工作台_需求文档.md`（v0.3）。

v0.3 在 v0.2 审核调度基线之上新增「从创意文本到成片」的分阶段创作链路：
**创意简报 → 故事方案 → 结构化剧本（卡点 A）→ 生产设定 + 结构化提示词（卡点 B）→ 分镜图片（卡点 C）→ 逐镜视频采用（卡点 D）→ 成片**。

## 启动

```powershell
python -m workbench            # 打开 http://127.0.0.1:8770
python -m workbench.seed       # （可选）一键导入 outputs/ 下 csr / c3 / 旧审核台数据
python -m workbench.worker     # （可选）独立 Worker 进程（默认 Worker 随服务启动）
python -m unittest workbench.tests.test_workbench workbench.tests.test_creative   # 测试（37 个用例）
```

依赖：`fastapi uvicorn sqlalchemy jinja2 pillow httpx python-multipart`（当前环境已具备）。
可选：`ffmpeg`（成片合成 / 抽帧 / 视频缩略图需要；缺失时相关任务会给出明确报错）。

## 三种入口（§2）

1. **创意模式**（v0.3 新增）：首页「① 创意模式」输入一段 ≥50 字描述与可选约束，
   系统依次生成故事方案与剧本（可逐场编辑），A 卡点批准后提取生产设定与结构化提示词；
2. **剧本模式**：粘贴剧本文本自动分镜（镜表 / 结构化 / 叙事三种格式自动识别）；
3. **分镜模式**：扫描目录 / 旧审核台 JSON / 约定清单导入，直接进入审核与生成。

## 文本模型（§10.5）

配置入口（二选一）：

- **设置页（推荐）**：「设置 → 文本模型（LLM）」直接选择类型、填写地址/模型/Key，
  保存即生效（无需重启）并可一键「测试连接」；配置持久化到 `workbench/config.json`，API Key 不回显；
- **配置文件/环境变量**：`workbench/config.json`（环境变量 `WORKBENCH_LLM_*` 同义，优先级 file > env > 默认）：

```json
{
  "llm_type": "mock",
  "llm_base_url": "https://api.example.com/v1",
  "llm_model": "your-model",
  "llm_api_key": "sk-...",
  "llm_max_repair": 2
}
```

- `llm_type=mock`（默认）：内置离线模型，确定性生成全链路结构化产物，零外部依赖；
- `llm_type=openai`：任意 OpenAI-compatible `/chat/completions` 接口；
- 四阶段（StoryPlan/Script/Bible/ShotPlans）强制 JSON Schema 校验，失败自动修复最多 2 次，
  仍失败保留原始输出并明确报错，不创建残缺下游实体；
- 每个版本记录模型、模板版本、输入指纹与审核决定（可追溯，验收 29）。

## 人工卡点 A~D（§6.11）

- **A 剧本审核**（`/projects/{id}/creative`）：编辑产生新版本，批准后放行生产设定；
- **B 生产包审核**（`/projects/{id}/bible`）：审核圣经/镜表/提示词/风险路径；支持整包批准、
  单镜批准/退回（需填原因），退回后可仅重做该镜（验收 21）；
- **C 图片审核**：图片批准是视频生成的硬前置（FR-GATE-001）；可开启「C 通过后自动排队」（验收 22）；
- **D 视频审核**：逐镜对比采用最终版本；
- A/B 卡点可按项目关闭；C/D 强制开启；全部状态持久化，重启可恢复（验收 23）。

## 精准失效（§7）

上游变化只使真正依赖它的下游标记 `stale`（带原因、可查看），旧版本与旧分支全部保留：
修改角色设定 → 仅引用该角色的镜头过期（验收 24）；换已批准图片 → 依赖视频过期（验收 25）；
修改对白 → 配音与口型视频过期；修改视频提示词不影响已批准图片。

## 风险识别与生成建议（FR-CREATIVE-005 / 验收 26）

系统侧确定性检测八类高风险镜头（手与物体接触、多人交互、复杂工具、可读文字、物体凭空变化、
长动作、口型同步、状态变化），并给出工作流建议（VACE 局部修补 / MoCha / 拆分短镜 / 首尾帧等），
用户保留覆盖权。

## 核心用法（v0.2 基线）

1. **项目**：首页创建或导入（旧审核台 JSON / 扫描 outputs 目录 / 约定清单 JSON）；
2. **分镜工作台**：卡片展示图片/提示词/音频/视频/状态/版本；筛选、批量批准、批量提交生成、导出审核清单 CSV；
3. **审核**：批准图片 → 提交视频生成 → 预览 → 采用为最终版 / 退回修改；
4. **版本**：每次生成/导入都是新版本（v1、v2、v3…），永不覆盖；对比页支持双视频同步播放与提示词 diff；
5. **任务中心**：排队/运行/失败/取消全状态，优先级调整、失败重试、相同参数重跑、日志查看、心跳监控；
6. **工作流与节点**：登记多个 ComfyUI 地址（本地/WSL/远程），导入 API 格式 workflow JSON 并配置参数映射；
   生成时可选模型（`model_name` 映射写入 workflow 图并记入版本快照）；
7. **成片**：全部分镜选定最终版本后可正式合成（FFmpeg 归一化 + 拼接 + 可选配乐），未就绪时可强制出预览版。

### 离线演示（无 ComfyUI 时验证流程）

「工作流与节点」→ 登记节点 → 类型选 **Mock（离线演示）**。
Mock 节点会真实产出：图片（Pillow 渐变图）、音频（静音 WAV）、视频（复制 outputs/ 样例或 ffmpeg 生成）。

## ComfyUI 对接（FR-COMFY）

- 工作流模板粘贴 **API 格式** JSON（ComfyUI 里「导出（API）」），映射格式：

```json
{
  "prompt": "12.inputs.text",
  "negative": "13.inputs.text",
  "seed": "24.inputs.seed",
  "input_image": "5.inputs.image",
  "model_name": "4.inputs.ckpt_name",
  "output_prefix": "31.inputs.filename_prefix"
}
```

可用业务字段：`prompt / negative / seed / width / height / fps / frames / duration /
input_image / model_name / output_prefix / voice_text / ambience_text`。

- 提交流程：上传输入图（`/upload/image`）→ `/prompt` → 轮询 `/queue` + `/history` → `/view` 下载输出；
- `output_prefix` 自动带项目/分镜/版本路径，输出按 §9 目录落盘并登记资产；
- 节点离线时任务保留在队列（验收 11）；服务重启后凭 `external_job_id` 重新同步历史；
- 安全（FR-COMFY-004 / §11.4）：默认仅监听 127.0.0.1，地址只存后端 SQLite，媒体访问限制在工作区根目录内。

## 配置（workbench/config.json，可选）

```json
{
  "port": 8770,
  "worker_concurrency": 1,
  "poll_interval": 2.0,
  "ffmpeg_bin": "ffmpeg",
  "llm_type": "mock",
  "htmx_url": "https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js"
}
```

环境变量同义覆盖：`WORKBENCH_PORT`、`WORKBENCH_WORKSPACE_ROOT`、`WORKBENCH_LLM_API_KEY` 等。
HTMX 从 CDN 加载，离线时可下载到 `workbench/static/htmx.min.js` 并配置 `htmx_url: "/static/htmx.min.js"`。

## 数据位置

- `workbench/data/workbench.db`：SQLite（§8 全部实体：项目/分镜/版本/任务/审核 +
  v0.3 创作实体 CreativeBrief/StoryScript/Scene/ProductionBible/PromptPackage/ApprovalGate/Dependency）；
- `workbench/data/thumbs/`、`workbench/data/joblogs/`：缩略图与任务日志缓存；
- `{workspace}/projects/{project_id}/`：§9 建议目录（brief/script/production_bible/shots/final/logs…）；
- 数据库只存路径与哈希，媒体文件不进 SQLite；旧库自动列迁移，兼容 v0.1/v0.2 数据。

## 约定导入清单格式（manifest）

```json
{
  "name": "示例", "aspect_ratio": "9:16", "resolution": "704x1216", "fps": 24,
  "shots": [
    {"code": "S01", "title": "开场", "duration": 8, "characters": "主角",
     "image_prompt": "...", "video_prompt": "...", "voice_text": "...",
     "image": "outputs/x/S01.png", "videos": ["outputs/x/S01.mp4"]}
  ]
}
```

## 已知边界（v0.3）

- ComfyUI 实时进度暂用 2s 轮询（§11.2 的 WebSocket/SSE 推送列入 v0.3-C 后续）；
- 远程 GPU 实例启停、SSH 密钥管理不在范围内（节点只登记 HTTP 地址）；
- 转场仅硬切（配置已预留字段）；字幕/片头片尾仅资产存储；
- 前景保护遮罩（FR-CHAR-003）仅存储与预览，不自动抠像；
- 对白镜配音草稿（B 卡点前锁时长，FR-GATE-002）任务类型已预留（voice），默认流程未强制；
- 自动模型推荐未实现，模型由人工选择；
- 本机无 ffmpeg 时：合成/抽帧任务失败（报错明确）、视频无缩略图（界面显示占位）。
