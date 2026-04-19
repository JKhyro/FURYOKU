import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ADAPTER = Path(__file__).resolve().parents[1] / "examples" / "hermes_bridge_hermes_runtime.py"


def bridge_payload() -> dict:
    return {
        "schemaVersion": 1,
        "bridge": "hermes-furyoku",
        "mode": "live",
        "envelope": {
            "schemaVersion": 1,
            "symbioteId": "symbiote-01",
            "role": "primary",
            "task": {
                "taskId": "hermes.bridge.one-symbiote",
                "requiredCapabilities": {
                    "conversation": 0.8,
                    "instruction_following": 0.8,
                },
                "privacyRequirement": "prefer_local",
            },
            "prompt": "Confirm the live Hermes bridge.",
            "routing": {
                "checkHealth": True,
                "fallback": True,
                "maxAttempts": 2,
            },
            "executionKey": "symbiote-01:primary:hermes.bridge.one-symbiote",
        },
        "selectedModel": {
            "modelId": "local-echo",
            "provider": "local",
            "eligible": True,
            "score": 1.0,
            "reasons": [],
            "blockers": [],
        },
        "decisionReport": {},
        "readiness": [],
    }


class HermesRuntimeAdapterTests(unittest.TestCase):
    def test_adapter_invokes_hermes_chat_with_bridge_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            argv_path = temp_path / "argv.json"
            fake_hermes = temp_path / "fake_hermes.py"
            fake_hermes.write_text(
                "import json, pathlib, sys\n"
                "pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]), encoding='utf-8')\n"
                "print('Hermes bridge received task.')\n",
                encoding="utf-8",
            )
            command_json = json.dumps([sys.executable, str(fake_hermes), str(argv_path)])

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ADAPTER),
                    "--hermes-command-json",
                    command_json,
                    "--provider",
                    "auto",
                    "--max-turns",
                    "1",
                ],
                input=json.dumps(bridge_payload()),
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            argv = json.loads(argv_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["adapter"], "hermes-bridge-hermes-runtime")
        self.assertEqual(payload["runtime"], "hermes-agent")
        self.assertEqual(payload["executionKey"], "symbiote-01:primary:hermes.bridge.one-symbiote")
        self.assertEqual(payload["selectedModelId"], "local-echo")
        self.assertIn("Hermes bridge received task.", payload["responseText"])
        self.assertIn("chat", argv)
        self.assertIn("--query", argv)
        self.assertIn("Confirm the live Hermes bridge.", argv)
        self.assertIn("--provider", argv)
        self.assertIn("auto", argv)
        self.assertIn("--model", argv)
        self.assertIn("local-echo", argv)

    def test_adapter_returns_structured_error_when_hermes_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_hermes = temp_path / "fake_hermes_fail.py"
            fake_hermes.write_text(
                "import sys\n"
                "sys.stderr.write('no provider configured')\n"
                "sys.exit(7)\n",
                encoding="utf-8",
            )
            command_json = json.dumps([sys.executable, str(fake_hermes)])

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ADAPTER),
                    "--hermes-command-json",
                    command_json,
                    "--max-turns",
                    "1",
                ],
                input=json.dumps(bridge_payload()),
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 7)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["exitCode"], 7)
        self.assertEqual(payload["stderr"], "no provider configured")
        self.assertEqual(payload["error"]["code"], "hermes_execution_failed")

    def test_adapter_reports_hermes_stdout_failure_even_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_hermes = temp_path / "fake_hermes_soft_fail.py"
            fake_hermes.write_text(
                "print('API call failed after 3 retries: quota exceeded')\n"
                "print('Final error: quota exceeded')\n",
                encoding="utf-8",
            )
            command_json = json.dumps([sys.executable, str(fake_hermes)])

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ADAPTER),
                    "--hermes-command-json",
                    command_json,
                    "--max-turns",
                    "1",
                ],
                input=json.dumps(bridge_payload()),
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["exitCode"], 0)
        self.assertIn("quota exceeded", payload["stdout"])
        self.assertEqual(payload["error"]["code"], "hermes_reported_failure")

    def test_adapter_rejects_malformed_bridge_payload(self):
        completed = subprocess.run(
            [sys.executable, str(ADAPTER), "--hermes-command-json", json.dumps([sys.executable])],
            input=json.dumps({"envelope": {}}),
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "invalid_bridge_payload")


if __name__ == "__main__":
    unittest.main()
