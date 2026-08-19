import json
import tempfile
import unittest
from pathlib import Path

from studio import app as studio_app


class StudioAppTests(unittest.TestCase):
    def test_workspace_path_accepts_project_media(self):
        path = studio_app.resolve_workspace_path("outputs/forest_fire/取火篇_704p_final.mp4")
        self.assertTrue(path.exists())

    def test_workspace_path_rejects_parent_escape(self):
        with self.assertRaises(Exception):
            studio_app.resolve_workspace_path("../outside.txt")

    def test_atomic_json_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            studio_app.atomic_write_json(path, {"title": "取火篇", "segments": [1, 2]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["segments"], [1, 2])


if __name__ == "__main__":
    unittest.main()
