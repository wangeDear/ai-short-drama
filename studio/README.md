# Project023 导演审核台（MVP）

这是一个零构建步骤的本地单用户 Web 工作台，用于验证以下闭环：

1. 查看每个视频段的分镜预览和提示词
2. 确认或退回分镜
3. 提交单段视频生成
4. 预览全部候选视频版本
5. 选择正式采用的版本
6. 保存审核备注与状态

## 启动

在项目根目录执行：

```powershell
python studio/app.py
```

浏览器打开：<http://127.0.0.1:8765>

FastAPI 与 Uvicorn 已存在于当前工作区 Python 环境；如果换到新环境：

```powershell
python -m pip install fastapi uvicorn
```

## 数据

`studio/data/project.json` 是当前项目清单与审核状态。MVP 已导入：

- `outputs/forest_fire/取火篇_704p_final.mp4`
- `outputs/forest_fire/shots_704p/` 下的 18 个分段视频

当前仓库没有服务器生产脚本和关键帧，所以界面暂时用已有视频的首帧作为分镜预览，提示词显示待同步占位文案。

## 接入生成脚本

复制配置示例：

```powershell
Copy-Item studio/config.example.json studio/config.json
```

编辑 `studio/config.json`：

- `enabled` 改为 `true`
- `command` 必须是参数数组，应用使用 `shell=False` 执行
- 支持 `{job_id}`、`{segment_id}`、`{manifest_path}`、`{workspace}` 占位符
- `output_path` 必须是相对项目根目录的最终视频路径

每次生成都会在 `studio/data/jobs/<job-id>/manifest.json` 写入完整分段输入，并把日志保存为 `runner.log`。

## MVP 限制

- 任务状态是本机单进程版；应用重启不会重新附着到正在执行的本地进程
- 取消只终止本机 Runner 进程，远端 ComfyUI 还需后续增加取消接口
- 尚未加入黑帧、时长、分辨率自动质检
- 尚未接入 Project023 的转场、调色、音频和最终拼接命令
- 一个页面只管理一个项目清单
