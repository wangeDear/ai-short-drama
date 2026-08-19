from __future__ import annotations

"""端到端测试：覆盖需求文档 §12 MVP 验收标准的核心链路。

用 Mock 生成节点替代 ComfyUI，验证：多项目、审核、生成、版本不覆盖、
最终版本选择、成片条件、导入、路径安全、状态联动与任务恢复。
注意：SQLite 单写者，测试中不要在持有 DB 会话时发起 HTTP 请求。
"""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ..config import Settings
from ..db import session_scope
from ..media import PathOutsideWorkspace, resolve_workspace_path
from ..models import GenerationJob, Project, Shot, ShotVersion
from ..services import jobs as jobs_service
from ..services import versions as versions_service
from ..services import workflows as workflows_service
from ..services.endpoints import create_endpoint
from ..web.main import create_app
from ..worker import run_once

MP4_BYTES = (
    b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    b"\x00\x00\x00\x08free"
) * 40


class WorkbenchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.workspace = root / "workspace"
        (self.workspace / "outputs").mkdir(parents=True)
        (self.workspace / "outputs" / "sample.mp4").write_bytes(MP4_BYTES)
        self.settings = Settings(
            {
                "workspace_root": str(self.workspace),
                "data_dir": str(root / "data"),
                "worker_enabled": "false",
                "ffmpeg_bin": "missing_ffmpeg_for_test",
                "ffprobe_bin": "missing_ffprobe_for_test",
                "poll_interval": 0.05,
            }
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass
        engine = getattr(self.app.state, "engine", None)
        if engine is not None:
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001
                pass
        self._tmp.cleanup()

    # ------------------------------------------------------------- helpers
    def db(self):
        return session_scope(self.app.state.session_factory)

    def post(self, path: str, data: dict) -> None:
        response = self.client.post(path, data=data, follow_redirects=False)
        assert response.status_code == 303, f"{path} -> {response.status_code}: {response.text[:200]}"

    def add_project(self, name: str = "测试项目") -> Project:
        self.post("/api/projects/create", {"name": name, "resolution": "704x1216", "fps": "24"})
        with self.db() as session:
            return session.query(Project).filter_by(name=name).one()

    def add_mock_endpoint(self, name: str = "Mock 节点") -> str:
        with self.db() as session:
            endpoint = create_endpoint(session, name=name, endpoint_type="mock", base_url="")
            return endpoint.id

    def add_shot(self, project_id: str, code: str = "S01", prompt: str = "测试提示词") -> Shot:
        self.post(
            f"/api/projects/{project_id}/shots/create",
            {"shot_code": code, "title": f"场 {code}", "duration": "8",
             "video_prompt": prompt, "image_prompt": prompt},
        )
        with self.db() as session:
            return session.query(Shot).filter_by(project_id=project_id, shot_code=code).one()

    def register_image(self, shot_id: str) -> None:
        image_path = self.workspace / "outputs" / f"{shot_id}.png"
        Image.new("RGB", (64, 96), (30, 40, 50)).save(image_path)
        self.post(
            f"/api/shots/{shot_id}/register-file",
            {"version_type": "image", "file_path": f"outputs/{shot_id}.png", "label": "测试图"},
        )

    def register_video(self, shot_id: str, filename: str) -> None:
        (self.workspace / "outputs" / filename).write_bytes(MP4_BYTES)
        self.post(
            f"/api/shots/{shot_id}/register-file",
            {"version_type": "video", "file_path": f"outputs/{filename}", "label": "测试视频"},
        )

    def shot_status(self, shot_id: str) -> str:
        with self.db() as session:
            return session.get(Shot, shot_id).status

    # ---------------------------------------------------------------- tests
    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_pages_render(self) -> None:
        for path in ("/", "/jobs", "/workflows", "/settings"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_create_project_and_shots(self) -> None:
        project = self.add_project("甲项目")
        self.assertTrue((self.workspace / "projects" / project.id / "project.json").exists())
        self.add_shot(project.id, "S01")
        self.add_shot(project.id, "S02")
        response = self.client.get(f"/projects/{project.id}/shots")
        self.assertIn('">S01</a>', response.text)
        self.assertIn('">S02</a>', response.text)
        other = self.add_project("乙项目")
        response = self.client.get(f"/projects/{other.id}/shots")
        self.assertNotIn('">S01</a>', response.text)

    def test_import_legacy_studio(self) -> None:
        (self.workspace / "outputs" / "fr2_C001_00001_.mp4").write_bytes(MP4_BYTES)
        legacy = {
            "id": "legacy-1",
            "title": "Project023 导演审核台",
            "episode": {"title": "森林求生 · 测试篇", "description": "旧数据"},
            "segments": [
                {"id": "C001", "order": 1, "title": "场 C001", "duration": 8, "prompt": "旧提示词",
                 "versions": [{"id": "v1", "video_path": "outputs/fr2_C001_00001_.mp4", "label": "v8 产物"}]}
            ],
        }
        legacy_path = self.workspace / "legacy.json"
        legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        self.post("/api/projects/import", {"mode": "legacy", "path": str(legacy_path)})
        with self.db() as session:
            project = session.query(Project).filter(Project.name.contains("森林求生")).one()
            self.assertEqual(len(project.shots), 1)
            shot = project.shots[0]
            self.assertEqual(shot.shot_code, "C001")
            self.assertEqual(len(shot.versions), 1)
            self.assertEqual(shot.versions[0].version_type, "video")

    def test_scan_videos_import(self) -> None:
        folder = self.workspace / "outputs"
        for code in ("S01", "S02", "S10"):
            (folder / f"csr_{code}_00001_.mp4").write_bytes(MP4_BYTES)
        self.post("/api/projects/import", {"mode": "scan", "path": "outputs", "name": "财神爷被裁员"})
        with self.db() as session:
            project = session.query(Project).filter_by(name="财神爷被裁员").one()
            codes = [shot.shot_code for shot in project.shots]
            self.assertEqual(codes, ["S01", "S02", "S10"])  # 自然排序
            self.assertTrue(all(len(shot.versions) == 1 for shot in project.shots))

    def test_full_generation_flow_with_mock(self) -> None:
        """验收 6/7/8/9：批准图片→生成视频→重做不覆盖→选择最终版本。"""
        self.add_mock_endpoint()
        project = self.add_project("生成流程")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)

        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.assertEqual(self.shot_status(shot.id), "image_approved")

        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})
        self.assertTrue(run_once(self.app.state.session_factory, self.settings))

        with self.db() as session:
            job = session.query(GenerationJob).filter_by(shot_id=shot.id).one()
            self.assertEqual(job.status, "succeeded")
            version = session.get(ShotVersion, job.version_id)
            self.assertEqual(version.status, "reviewing")
            assets = versions_service.version_assets(session, version)
            self.assertTrue(any(a.asset_type == "video" for a in assets))
            v1_id = version.id

        # 重做：第二个版本（不覆盖旧版本）
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})
        self.assertTrue(run_once(self.app.state.session_factory, self.settings))

        with self.db() as session:
            video_versions = (
                session.query(ShotVersion)
                .filter(ShotVersion.shot_id == shot.id, ShotVersion.version_type == "video")
                .all()
            )
            self.assertEqual(len(video_versions), 2)
            v2 = max(video_versions, key=lambda v: v.version_number)
            v2_id = v2.id
            old = session.get(ShotVersion, v1_id)
            self.assertIsNotNone(old)
            self.assertTrue(all(v.assets or versions_service.version_assets(session, v) for v in video_versions))

        # 选择最终版本（验收 9）
        self.post(f"/api/shots/{shot.id}/select-version", {"version_id": v2_id})
        self.assertEqual(self.shot_status(shot.id), "accepted")
        with self.db() as session:
            shot_row = session.get(Shot, shot.id)
            self.assertEqual(shot_row.selected_version_id, v2_id)
            # 旧版本仍存在（验收 8）
            self.assertIsNotNone(session.get(ShotVersion, v1_id))

    def test_job_log_named_after_job_id(self) -> None:
        """回归：入队日志必须在 flush 后写入，以任务 ID 命名（不产生 None.log）。"""
        self.add_mock_endpoint()
        project = self.add_project("日志命名")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})
        with self.db() as session:
            job = session.query(GenerationJob).filter_by(shot_id=shot.id).one()
            job_id = job.id
        joblogs = Path(self.settings.joblogs_dir)
        self.assertTrue((joblogs / f"{job_id}.log").exists())
        self.assertFalse((joblogs / "None.log").exists(), "入队日志不得写入 None.log")

    def test_rerun_creates_new_version_and_completes(self) -> None:
        """回归：相同参数重跑需关联新版本并成功产出，不覆盖旧文件（FR-JOB-004）。"""
        self.add_mock_endpoint()
        project = self.add_project("重跑")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})
        self.assertTrue(run_once(self.app.state.session_factory, self.settings))

        with self.db() as session:
            job = session.query(GenerationJob).filter_by(shot_id=shot.id, status="succeeded").one()
            first_job_id = job.id
            v1 = session.get(ShotVersion, job.version_id)
            v1_file = versions_service.version_assets(session, v1)[0].file_path
            v1_path = resolve_workspace_path(self.workspace, v1_file)
            v1_bytes = v1_path.read_bytes()

        self.post(f"/api/jobs/{first_job_id}/rerun", {})
        self.assertTrue(run_once(self.app.state.session_factory, self.settings))

        with self.db() as session:
            rerun_job = (
                session.query(GenerationJob)
                .filter(GenerationJob.shot_id == shot.id, GenerationJob.id != first_job_id)
                .one()
            )
            self.assertEqual(rerun_job.status, "succeeded")
            self.assertIsNotNone(rerun_job.version_id, "重跑任务必须关联新版本")
            v2 = session.get(ShotVersion, rerun_job.version_id)
            self.assertEqual(v2.version_number, 2)
            self.assertEqual(v2.status, "reviewing")
            v2_assets = versions_service.version_assets(session, v2)
            self.assertTrue(any(a.asset_type == "video" for a in v2_assets))
            # 旧版本文件未被覆盖（FR-VER-001）
            self.assertEqual(v1_path.read_bytes(), v1_bytes)
            v2_file = next(a for a in v2_assets if a.asset_type == "video").file_path
            self.assertNotEqual(v2_file, v1_file)

    def test_prompt_edit_invalidation_rules(self) -> None:
        """§7-2：修改视频提示词不使已批准图片失效。"""
        project = self.add_project("状态联动")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.assertEqual(self.shot_status(shot.id), "image_approved")

        self.post(f"/api/shots/{shot.id}/update", {"video_prompt": "新视频提示词"})
        self.assertEqual(self.shot_status(shot.id), "image_approved")

    def test_image_prompt_edit_invalidates(self) -> None:
        """§7-1：修改图片提示词 -> 图片需重审、下游视频配置过期。"""
        project = self.add_project("图片联动")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)
        self.register_video(shot.id, "v1.mp4")
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})

        with self.db() as session:
            shot_row = session.get(Shot, shot.id)
            selected = [v for v in shot_row.versions if v.version_type == "video"][0]
            self.post(f"/api/shots/{shot.id}/select-version", {"version_id": selected.id})

        self.post(f"/api/shots/{shot.id}/update", {"image_prompt": "改了图片提示词"})
        with self.db() as session:
            shot_row = session.get(Shot, shot.id)
            self.assertEqual(shot_row.status, "image_review")
            self.assertTrue(shot_row.video_config_stale)

    def test_voice_text_edit_invalidates_audio(self) -> None:
        """§7-3：修改配音文本 -> 已批准配音版本失效，图片状态不受影响。"""
        project = self.add_project("配音联动")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)
        audio_path = self.workspace / "outputs" / f"{shot.id}.wav"
        audio_path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00")
        self.post(
            f"/api/shots/{shot.id}/register-file",
            {"version_type": "audio", "file_path": f"outputs/{shot.id}.wav", "label": "配音v1"},
        )
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_audio"})
        with self.db() as session:
            shot_row = session.get(Shot, shot.id)
            audio = versions_service.latest_version(session, shot_row, "audio")
            self.assertEqual(audio.status, "accepted")

        self.post(f"/api/shots/{shot.id}/update", {"voice_text": "新配音文本"})

        with self.db() as session:
            shot_row = session.get(Shot, shot.id)
            audio = versions_service.latest_version(session, shot_row, "audio")
            self.assertEqual(audio.status, "draft")
            self.assertEqual(shot_row.status, "image_approved")  # 图片不受影响
            self.assertEqual(shot_row.voice_text, "新配音文本")

    def test_final_compose_readiness_and_failure(self) -> None:
        project = self.add_project("成片")
        shot = self.add_shot(project.id)
        self.register_video(shot.id, "final_src.mp4")

        with self.db() as session:
            shot_row = session.get(Shot, shot.id)
            version = [v for v in shot_row.versions if v.version_type == "video"][0]
            version_id = version.id
        self.post(f"/api/shots/{shot.id}/select-version", {"version_id": version_id})

        with self.db() as session:
            from ..services.final import readiness

            state = readiness(session, session.get(Project, project.id))
            self.assertTrue(state["ready"])

        self.post(
            f"/api/projects/{project.id}/final/compose",
            {"resolution": "704x1216", "fps": "24", "crf": "20", "preset": "medium"},
        )
        # 无 ffmpeg 时任务失败且报错清晰（本机测试环境未装 ffmpeg）
        self.assertTrue(run_once(self.app.state.session_factory, self.settings))
        with self.db() as session:
            job = session.query(GenerationJob).filter_by(project_id=project.id).one()
            self.assertEqual(job.job_type, "compose")
            if not _ffmpeg_exists():
                self.assertEqual(job.status, "failed")
                self.assertIn("ffmpeg", job.error_message)

    def test_compose_requires_selection_or_force(self) -> None:
        project = self.add_project("成片条件")
        self.add_shot(project.id)
        response = self.client.post(
            f"/api/projects/{project.id}/final/compose", data={}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("err=", response.headers["location"])
        response = self.client.post(
            f"/api/projects/{project.id}/final/compose",
            data={"force": "on"}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=", response.headers["location"])

    def test_cancel_queued_job(self) -> None:
        self.add_mock_endpoint()
        project = self.add_project("取消")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})
        with self.db() as session:
            job = session.query(GenerationJob).filter_by(shot_id=shot.id).one()
            job_id = job.id
        self.post(f"/api/jobs/{job_id}/cancel", {})
        with self.db() as session:
            self.assertEqual(session.get(GenerationJob, job_id).status, "cancelled")

    def test_recover_stale_jobs(self) -> None:
        project = self.add_project("恢复")
        with self.db() as session:
            job = GenerationJob(
                project_id=project.id, job_type="video", status="running",
                started_at=jobs_service.utcnow(),
                last_heartbeat_at=jobs_service.utcnow() - timedelta(minutes=99),
            )
            session.add(job)
            session.flush()
            job_id = job.id
        with self.db() as session:
            recovered = jobs_service.recover_stale(session, 15)
            self.assertIn(job_id, recovered)
            self.assertEqual(session.get(GenerationJob, job_id).status, "failed")

    def test_settings_llm_config(self) -> None:
        """设置页在线配置 LLM：写 config.json + 即时生效 + Key 不回显。"""
        import os
        from unittest import mock

        config_file = self.workspace / "config.json"
        env = {"WORKBENCH_CONFIG": str(config_file)}
        with mock.patch.dict(os.environ, env):
            # 页面渲染
            response = self.client.get("/settings")
            self.assertEqual(response.status_code, 200)
            self.assertIn("文本模型", response.text)

            # 非法类型被拒
            response = self.client.post(
                "/api/settings/llm", data={"llm_type": "bogus"}, follow_redirects=False
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("err=", response.headers["location"])

            # openai 缺地址被拒
            response = self.client.post(
                "/api/settings/llm", data={"llm_type": "openai", "llm_model": "m"}, follow_redirects=False
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("err=", response.headers["location"])

            # 保存 openai 配置：文件落盘 + 内存即时生效
            response = self.client.post(
                "/api/settings/llm",
                data={
                    "llm_type": "openai",
                    "llm_base_url": "https://api.example.com/v1/",
                    "llm_model": "glm-4.7",
                    "llm_api_key": "sk-test-123456789",
                    "llm_timeout_seconds": "120",
                    "llm_max_repair": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("msg=", response.headers["location"])
            saved = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["llm_type"], "openai")
            self.assertEqual(saved["llm_base_url"], "https://api.example.com/v1")
            self.assertEqual(self.settings.llm_type, "openai")
            self.assertEqual(self.settings.llm_base_url, "https://api.example.com/v1")
            self.assertEqual(self.settings.llm_model, "glm-4.7")
            self.assertEqual(self.settings.llm_api_key, "sk-test-123456789")
            self.assertEqual(self.settings.llm_timeout_seconds, 120.0)
            self.assertEqual(self.settings.llm_max_repair, 1)

            # Key 不回显，仅掩码
            response = self.client.get("/settings")
            self.assertNotIn("sk-test-123456789", response.text)
            self.assertIn("sk-t…6789", response.text)

            # 切回 mock：Key 留空保持，数值留空恢复默认（键删除）
            response = self.client.post(
                "/api/settings/llm",
                data={
                    "llm_type": "mock",
                    "llm_base_url": "", "llm_model": "", "llm_api_key": "",
                    "llm_timeout_seconds": "", "llm_max_repair": "",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            saved = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["llm_type"], "mock")
            self.assertNotIn("llm_base_url", saved)
            self.assertNotIn("llm_timeout_seconds", saved)
            self.assertEqual(saved["llm_api_key"], "sk-test-123456789")
            self.assertEqual(self.settings.llm_type, "mock")
            self.assertEqual(self.settings.llm_api_key, "sk-test-123456789")
            self.assertEqual(self.settings.llm_timeout_seconds, 180.0)
            self.assertEqual(self.settings.llm_max_repair, 2)

            # 测试连接：mock 直接成功
            response = self.client.post("/api/settings/llm/test", data={}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertIn("msg=", response.headers["location"])

            # 测试连接：openai 指向不可达地址 → 明确报错（不抛异常）
            self.settings.llm_type = "openai"
            self.settings.llm_base_url = "http://127.0.0.1:9/v1"
            self.settings.llm_model = "m"
            self.settings.llm_api_key = ""
            self.settings.llm_timeout_seconds = 3.0
            response = self.client.post("/api/settings/llm/test", data={}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertIn("err=", response.headers["location"])

            # 清除 Key
            response = self.client.post(
                "/api/settings/llm", data={"llm_type": "mock", "clear_api_key": "on"}, follow_redirects=False
            )
            self.assertEqual(response.status_code, 303)
            saved = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertNotIn("llm_api_key", saved)
            self.assertEqual(self.settings.llm_api_key, "")

    def test_settings_llm_security(self) -> None:
        """安全修复：CSRF 拦截、换址重验 Key、损坏配置拒绝合并、/media 不泄漏配置。"""
        import os
        from unittest import mock

        config_file = self.workspace / "config.json"
        env = {"WORKBENCH_CONFIG": str(config_file)}
        with mock.patch.dict(os.environ, env):
            # 跨站 Origin 直接拒绝，不写文件
            response = self.client.post(
                "/api/settings/llm",
                data={"llm_type": "mock"},
                headers={"Origin": "http://evil.example"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("err=", response.headers["location"])
            self.assertFalse(config_file.exists())
            response = self.client.post(
                "/api/settings/llm/test", data={}, headers={"Referer": "http://evil.example/x"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("err=", response.headers["location"])

            # 同源 Origin 放行
            response = self.client.post(
                "/api/settings/llm",
                data={"llm_type": "openai", "llm_base_url": "https://api.example.com/v1",
                      "llm_model": "m", "llm_api_key": "sk-keep"},
                headers={"Origin": "http://testserver"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("msg=", response.headers["location"])

            # 已保存 Key 时更换地址且未重输 Key → 拒绝
            response = self.client.post(
                "/api/settings/llm",
                data={"llm_type": "openai", "llm_base_url": "http://attacker.example/v1",
                      "llm_model": "m", "llm_api_key": ""},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("err=", response.headers["location"])
            saved = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["llm_base_url"], "https://api.example.com/v1")

            # 损坏的 config.json → 拒绝合并且文件保持原样
            config_file.write_text("{ not json", encoding="utf-8")
            response = self.client.post(
                "/api/settings/llm", data={"llm_type": "mock"}, follow_redirects=False
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("err=", response.headers["location"])
            self.assertEqual(config_file.read_text(encoding="utf-8"), "{ not json")

            # /media 不能下载配置文件（即使位于 workspace 内）；普通素材不受影响
            config_file.write_text('{"llm_api_key": "sk-secret"}', encoding="utf-8")
            response = self.client.get("/media/config.json")
            self.assertEqual(response.status_code, 403)
            (self.workspace / "outputs" / "media_ok.txt").write_text("ok", encoding="utf-8")
            response = self.client.get("/media/outputs/media_ok.txt")
            self.assertEqual(response.status_code, 200)

    def test_delete_project(self) -> None:
        """永久删除：清库记录、可选删生成文件、源文件保留、活动任务拦截。"""
        from ..models import Asset as AssetRow
        from ..models import Review as ReviewRow

        project = self.add_project("待删除")
        shot = self.add_shot(project.id, "S01")
        self.register_image(shot.id)
        self.register_video(shot.id, "del_v1.mp4")
        other = self.add_project("保留项目")

        project_dir = self.workspace / "projects" / project.id
        self.assertTrue(project_dir.exists())

        # 有排队任务时拒绝删除
        self.add_mock_endpoint()
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})
        response = self.client.post(
            f"/api/projects/{project.id}/delete", data={"delete_files": "on"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("err=", response.headers["location"])
        with self.db() as session:
            self.assertIsNotNone(session.get(Project, project.id))

        # 取消任务后删除成功（含生成文件）
        with self.db() as session:
            job = session.query(GenerationJob).filter_by(shot_id=shot.id).one()
            job_id = job.id
        self.post(f"/api/jobs/{job_id}/cancel", {})
        response = self.client.post(
            f"/api/projects/{project.id}/delete", data={"delete_files": "on"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/?msg="))

        with self.db() as session:
            self.assertIsNone(session.get(Project, project.id))
            self.assertEqual(
                session.query(Shot).filter_by(project_id=project.id).count(), 0
            )
            self.assertEqual(
                session.query(ShotVersion).join(Shot, ShotVersion.shot_id == Shot.id)
                .filter(Shot.project_id == project.id).count(), 0
            )
            self.assertEqual(
                session.query(GenerationJob).filter_by(project_id=project.id).count(), 0
            )
            self.assertEqual(
                session.query(ReviewRow).filter_by(project_id=project.id).count(), 0
            )
            self.assertEqual(
                session.query(AssetRow).filter_by(project_id=project.id).count(), 0
            )
            # 其他项目不受影响
            self.assertIsNotNone(session.get(Project, other.id))

        # 生成的项目目录已删除，导入源文件保留
        self.assertFalse(project_dir.exists())
        self.assertTrue((self.workspace / "outputs" / "del_v1.mp4").exists())
        self.assertTrue((self.workspace / "outputs" / f"{shot.id}.png").exists())

    def test_delete_project_with_creative_entities(self) -> None:
        """回归：含 v0.3 创作实体（简报/剧本/场景/圣经/卡点/提示词包/依赖）的项目可删除。

        这些表无 ORM 级联，删除前未清理会触发 SQLite 外键约束失败（500）。
        """
        from ..models import (
            ApprovalGate,
            CreativeBriefVersion,
            DependencyEdge,
            ProductionBibleVersion,
            PromptPackage,
            Scene,
            StoryScriptVersion,
        )

        project = self.add_project("创作链路删除")
        shot = self.add_shot(project.id, "S01")
        with self.db() as session:
            session.add(CreativeBriefVersion(project_id=project.id, source_text="测试创意" * 20))
            script = StoryScriptVersion(project_id=project.id, version_type="script")
            session.add(script)
            session.flush()
            session.add(Scene(project_id=project.id, script_version_id=script.id))
            session.add(ProductionBibleVersion(project_id=project.id))
            session.add(ApprovalGate(project_id=project.id, gate_type="A"))
            session.add(PromptPackage(shot_id=shot.id))
            session.add(DependencyEdge(project_id=project.id))

        response = self.client.post(
            f"/api/projects/{project.id}/delete", data={"delete_files": "on"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/?msg="))
        with self.db() as session:
            self.assertIsNone(session.get(Project, project.id))
            for model in (CreativeBriefVersion, StoryScriptVersion, Scene,
                          ProductionBibleVersion, ApprovalGate, DependencyEdge):
                self.assertEqual(
                    session.query(model).filter_by(project_id=project.id).count(), 0, model.__tablename__
                )
            self.assertEqual(
                session.query(PromptPackage).filter_by(shot_id=shot.id).count(), 0
            )

    def test_openai_adapter_generate_structured(self) -> None:
        """回归：openai 适配器必须继承 BaseLLMAdapter.generate_structured（结构化校验+修复循环）。"""
        from unittest import mock as _mock

        from ..llm import BaseLLMAdapter, get_llm_adapter
        from ..llm.openai_compat import OpenAICompatAdapter

        adapter = get_llm_adapter("openai")
        self.assertIsInstance(adapter, BaseLLMAdapter)

        settings = Settings({"llm_max_repair": 1, "llm_model": "test-model"})
        schema = {
            "type": "object", "required": ["title"],
            "properties": {"title": {"type": "string", "minLength": 2}},
        }
        replies = iter(['{"title": "x"}', '{"title": "ok title", "scenes": []}'])
        with _mock.patch.object(
            OpenAICompatAdapter, "chat", side_effect=lambda s, sys_, usr: next(replies)
        ):
            result = adapter.generate_structured(
                settings, stage="script", system="", user="u",
                schema=schema, context={}, template_version="v1",
            )
        self.assertEqual(result.data["title"], "ok title")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.repaired, 1)

        # 修复次数耗尽仍非法 → LLMError
        with _mock.patch.object(OpenAICompatAdapter, "chat", return_value="not json"):
            with self.assertRaises(Exception):
                adapter.generate_structured(
                    settings, stage="script", system="", user="u",
                    schema=schema, context={}, template_version="v1",
                )

    def test_model_selection_flow(self) -> None:
        """生成时选择模型：持久化到分镜参数、注入 workflow 图、记录进版本快照。"""
        from ..models import WorkflowTemplate
        from ..services.endpoints import fetch_models, get_endpoint

        endpoint_id = self.add_mock_endpoint()
        with self.db() as session:
            template = WorkflowTemplate(
                name="模型映射测试模板",
                category="h3_i2v",
                workflow_json={
                    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "default.safetensors"}},
                    "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}},
                },
                parameter_mapping_json={
                    "prompt": "12.inputs.text",
                    "model_name": "4.inputs.ckpt_name",
                },
                enabled=True,
            )
            session.add(template)
        with self.db() as session:
            # Mock 节点可以拉取模型列表
            models = fetch_models(session, self.settings, get_endpoint(session, endpoint_id))
            self.assertIn("mock_h3_video.safetensors", models)

        project = self.add_project("模型选择")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})

        # 生成时选择模型
        self.post(
            f"/api/shots/{shot.id}/generate",
            {"job_type": "video", "model_name": "mock_h3_video.safetensors"},
        )
        with self.db() as session:
            job = session.query(GenerationJob).filter_by(shot_id=shot.id).one()
            snapshot = job.request_snapshot
            self.assertEqual(snapshot["values"]["model_name"], "mock_h3_video.safetensors")
            # model_name 已写入 workflow 图的 CheckpointLoader 节点
            self.assertEqual(
                snapshot["workflow"]["graph"]["4"]["inputs"]["ckpt_name"],
                "mock_h3_video.safetensors",
            )
            # 分镜参数记忆了视频模型（下次生成默认选中）
            shot_row = session.get(Shot, shot.id)
            self.assertEqual(shot_row.params_json.get("video_model"), "mock_h3_video.safetensors")
            # 版本快照记录所用模型（FR-VER-002）
            version = session.get(ShotVersion, job.version_id)
            self.assertEqual(
                version.parameter_snapshot["params"]["video_model"],
                "mock_h3_video.safetensors",
            )

        # 编辑表单也可以改模型（image_model 触发图片环节失效）
        self.register_image(shot.id)
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.post(f"/api/shots/{shot.id}/update", {"image_model": "flux_dev.safetensors"})
        with self.db() as session:
            shot_row = session.get(Shot, shot.id)
            self.assertEqual(shot_row.params_json.get("image_model"), "flux_dev.safetensors")

    def test_script_table_import(self) -> None:
        """docs/07 同款 Markdown 镜表直接粘贴导入。"""
        table = (
            "| # | 镜型 | 时长 | 运镜/画面 | 台词（中文） | soundscape |\n"
            "|---|---|---|---|---|---|\n"
            '| S01 | 口型·自拍广角 | 10s | 鱼眼自拍，举起手机屏幕显示 2% 低电量 | "兄弟们，手机只剩百分之二的电，GPS信号也快没了。" | howling wind |\n'
            '| S02 | 操作·俯拍POV | 6s | 戴手套双手取出太阳能板平铺沙地 | （画外边做边说）"先试最简单的。" | velcro rip |\n'
            '| S03 | 口型·中景 |  | 中景，她摇头轻笑 | "木头支架一直抖，这么下去迟早得断。上专业装备。" | creaking wood |'
        )
        response = self.client.post(
            "/api/projects/import-script",
            data={"name": "沙漠·离网电力", "text": table, "default_seconds": "6", "target_seconds": "10"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text[:300])
        with self.db() as session:
            project = session.query(Project).filter_by(name="沙漠·离网电力").one()
            shots = sorted(project.shots, key=lambda s: s.sequence_index)
            self.assertEqual(len(shots), 3)
            self.assertEqual([s.shot_code for s in shots], ["S01", "S02", "S03"])
            self.assertEqual(shots[0].duration, 10.0)  # 显式 10s
            self.assertEqual(shots[1].duration, 6.0)
            # S03 无显式时长 -> 台词公式：23字÷4+2 = 7.8
            self.assertAlmostEqual(shots[2].duration, 7.8, places=1)
            self.assertIn("百分之二", shots[0].voice_text)
            self.assertEqual(shots[0].ambience_text, "howling wind")
            self.assertIn("太阳能板", shots[1].description)
            # seed 已派生且固定
            self.assertIsNotNone(shots[0].seed)

    def test_script_structured_and_narrative(self) -> None:
        structured = (
            "## 第一场 沙漠清晨\n"
            "她举起手机，屏幕显示 2% 电量。\n"
            "林夏：兄弟们，手机只剩百分之二的电。\n"
            "## 第二场 铺设太阳能板\n"
            "戴手套双手取出折叠太阳能板。"
        )
        response = self.client.post(
            "/api/projects/import-script",
            data={"name": "结构化剧本", "text": structured, "default_seconds": "6", "target_seconds": "10"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        with self.db() as session:
            project = session.query(Project).filter_by(name="结构化剧本").one()
            shots = sorted(project.shots, key=lambda s: s.sequence_index)
            self.assertEqual(len(shots), 2)
            self.assertIn("林夏", shots[0].characters)
            self.assertIn("百分之二", shots[0].voice_text)
            self.assertIn("沙漠清晨", shots[0].title)
            self.assertEqual(shots[1].duration, 6.0)  # 无台词 -> 默认时长

        narrative = "天空湛蓝。她背起背包走进沙漠。" + "风沙越来越大。" * 30
        response = self.client.post(
            "/api/projects/import-script",
            data={"name": "叙事文本", "text": narrative, "target_seconds": "8"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        with self.db() as session:
            project = session.query(Project).filter_by(name="叙事文本").one()
            self.assertGreater(len(project.shots), 2)

    def test_script_auto_image_submission(self) -> None:
        """勾选自动生图：创建后图片任务直接入队。"""
        self.add_mock_endpoint()
        script = "## S1 场\n她举起手机。\n林夏：只剩百分之二的电了。\n## S2 场\n她铺开太阳能板。"
        response = self.client.post(
            "/api/projects/import-script",
            data={
                "name": "自动生图", "text": script, "auto_image": "on",
                "default_seconds": "6", "target_seconds": "10",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        with self.db() as session:
            project = session.query(Project).filter_by(name="自动生图").one()
            jobs = session.query(GenerationJob).filter_by(project_id=project.id).all()
            self.assertEqual(len(jobs), 2)
            self.assertTrue(all(job.job_type == "image" for job in jobs))

    def test_video_generation_gated_by_image_approval(self) -> None:
        """人工审核卡点：没有已批准的分镜图，视频生成被拒绝。"""
        self.add_mock_endpoint()
        project = self.add_project("卡点测试")
        shot = self.add_shot(project.id)

        # 无图片 -> 拒绝
        response = self.client.post(
            f"/api/shots/{shot.id}/generate", data={"job_type": "video"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("err=", response.headers["location"])
        with self.db() as session:
            self.assertEqual(
                session.query(GenerationJob).filter_by(shot_id=shot.id).count(), 0
            )

        # 有图但未批准 -> 仍拒绝
        self.register_image(shot.id)
        response = self.client.post(
            f"/api/shots/{shot.id}/generate", data={"job_type": "video"}, follow_redirects=False
        )
        self.assertIn("err=", response.headers["location"])
        with self.db() as session:
            self.assertEqual(
                session.query(GenerationJob).filter_by(shot_id=shot.id).count(), 0
            )

        # 批准后 -> 放行
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})
        with self.db() as session:
            self.assertEqual(
                session.query(GenerationJob).filter_by(shot_id=shot.id).count(), 1
            )

    def test_imported_video_shot_bypasses_image_gate(self) -> None:
        """已导入视频的旧分镜可直接重做视频，不受图片卡点限制。"""
        self.add_mock_endpoint()
        project = self.add_project("重做导入分镜")
        shot = self.add_shot(project.id)
        self.register_video(shot.id, "redo_src.mp4")
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})
        with self.db() as session:
            self.assertEqual(
                session.query(GenerationJob).filter_by(shot_id=shot.id).count(), 1
            )

    def test_pipeline_stages_progression(self) -> None:
        """流水线卡点计数随人工推进逐级变化。"""
        from ..services.pipeline import pipeline_stages

        project = self.add_project("流水线")
        shot_a = self.add_shot(project.id, "S01")  # 有提示词
        shot_b = self.add_shot(project.id, "S02")

        with self.db() as session:
            stages = {s.key: s for s in pipeline_stages(session, session.get(Project, project.id))}
            self.assertEqual(stages["image_todo"].count, 2)  # 都可生图
            self.assertEqual(stages["image_pending"].count, 0)
            self.assertEqual(stages["video_ready"].count, 0)

        self.register_image(shot_a.id)
        self.register_image(shot_b.id)

        with self.db() as session:
            stages = {s.key: s for s in pipeline_stages(session, session.get(Project, project.id))}
            self.assertEqual(stages["image_pending"].count, 2)  # 两张待审
            self.assertEqual(stages["image_todo"].count, 0)

        self.post(f"/api/shots/{shot_a.id}/review", {"action": "approve_image"})
        with self.db() as session:
            stages = {s.key: s for s in pipeline_stages(session, session.get(Project, project.id))}
            self.assertEqual(stages["image_pending"].count, 1)  # B 仍待审
            self.assertEqual(stages["video_ready"].count, 1)  # A 可提交视频
            self.assertEqual(stages["selected"].count, 0)

        # B 也批准并导入视频 -> 进入视频待采用
        self.post(f"/api/shots/{shot_b.id}/review", {"action": "approve_image"})
        self.register_video(shot_b.id, "pipe_b.mp4")
        with self.db() as session:
            stages = {s.key: s for s in pipeline_stages(session, session.get(Project, project.id))}
            self.assertEqual(stages["video_pending"].count, 1)
            version = [v for v in session.get(Shot, shot_b.id).versions if v.version_type == "video"][0]
            version_id = version.id
        self.post(f"/api/shots/{shot_b.id}/select-version", {"version_id": version_id})
        with self.db() as session:
            stages = {s.key: s for s in pipeline_stages(session, session.get(Project, project.id))}
            self.assertEqual(stages["selected"].count, 1)

    def test_workflow_mapping_apply(self) -> None:
        graph = {"12": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}}}
        rendered = workflows_service.apply_mapping(graph, {"prompt": "12.inputs.text"}, {"prompt": "新提示词"})
        self.assertEqual(rendered["12"]["inputs"]["text"], "新提示词")
        self.assertEqual(graph["12"]["inputs"]["text"], "x")  # 原图不被修改

    def test_path_safety(self) -> None:
        with self.assertRaises(PathOutsideWorkspace):
            resolve_workspace_path(self.workspace, "../outside.txt")
        response = self.client.get("/media/..%2F..%2Fwindows%2Fwin.ini")
        self.assertIn(response.status_code, (403, 404))

    def test_worker_keeps_job_when_endpoint_offline(self) -> None:
        """验收 11：ComfyUI 离线时任务保留在队列。"""
        with self.db() as session:
            create_endpoint(session, name="离线 ComfyUI", endpoint_type="comfyui", base_url="http://127.0.0.1:59999")
        project = self.add_project("离线队列")
        shot = self.add_shot(project.id)
        self.register_image(shot.id)
        self.post(f"/api/shots/{shot.id}/review", {"action": "approve_image"})
        self.post(f"/api/shots/{shot.id}/generate", {"job_type": "video"})

        self.assertFalse(run_once(self.app.state.session_factory, self.settings))
        with self.db() as session:
            job = session.query(GenerationJob).filter_by(shot_id=shot.id).one()
            self.assertEqual(job.status, "queued")
            self.assertIn("离线", job.current_step)


def _ffmpeg_exists() -> bool:
    import shutil

    return shutil.which("ffmpeg") is not None


if __name__ == "__main__":
    unittest.main()
