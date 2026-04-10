import json
import tempfile
import unittest
from pathlib import Path

from furyoku import TaskProfileError, load_task_profile, parse_task_profile


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_TASK = ROOT / "examples" / "task_profile.private-chat.json"


class TaskProfileTests(unittest.TestCase):
    def test_load_example_task_profile(self):
        profile = load_task_profile(EXAMPLE_TASK)

        self.assertEqual(profile.task_id, "private-chat")
        self.assertEqual(profile.privacy_requirement, "local_only")
        self.assertEqual(profile.required_capabilities["conversation"], 0.8)

    def test_load_task_profile_accepts_utf8_bom_file(self):
        payload = {
            "schemaVersion": 1,
            "taskId": "bom-task",
            "requiredCapabilities": {"conversation": 0.8},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "task.json"
            path.write_text(json.dumps(payload), encoding="utf-8-sig")
            profile = load_task_profile(path)

        self.assertEqual(profile.task_id, "bom-task")

    def test_missing_capabilities_are_rejected(self):
        with self.assertRaises(TaskProfileError) as error:
            parse_task_profile({"schemaVersion": 1, "taskId": "broken"})

        self.assertIn("requiredCapabilities", str(error.exception))


if __name__ == "__main__":
    unittest.main()
