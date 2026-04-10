import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from furyoku.cli import main


def write_registry(path: Path) -> None:
    payload = {
        "schemaVersion": 1,
        "models": [
            {
                "modelId": "local-echo",
                "provider": "local",
                "privacyLevel": "local",
                "contextWindowTokens": 4096,
                "averageLatencyMs": 10,
                "invocation": [
                    sys.executable,
                    "-c",
                    "import sys; print('echo:' + sys.stdin.read())",
                ],
                "capabilities": {
                    "conversation": 0.95,
                    "instruction_following": 0.9,
                },
            },
            {
                "modelId": "remote-coder",
                "provider": "api",
                "privacyLevel": "remote",
                "contextWindowTokens": 128000,
                "averageLatencyMs": 100,
                "supportsTools": True,
                "capabilities": {
                    "conversation": 0.8,
                    "instruction_following": 0.9,
                    "coding": 0.98,
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class CliTests(unittest.TestCase):
    def test_select_outputs_selected_model_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            write_registry(registry_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "select",
                        "--registry",
                        str(registry_path),
                        "--task-id",
                        "private-chat",
                        "--capability",
                        "conversation=0.9",
                        "--privacy",
                        "local_only",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["modelId"], "local-echo")
            self.assertEqual(payload["provider"], "local")
            self.assertTrue(payload["eligible"])

    def test_run_executes_selected_local_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            write_registry(registry_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "run",
                        "--registry",
                        str(registry_path),
                        "--task-id",
                        "private-chat",
                        "--capability",
                        "conversation=0.9",
                        "--privacy",
                        "local_only",
                        "--prompt",
                        "hello",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["selection"]["modelId"], "local-echo")
            self.assertEqual(payload["execution"]["responseText"].strip(), "echo:hello")


if __name__ == "__main__":
    unittest.main()
