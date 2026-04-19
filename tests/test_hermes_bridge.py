import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from furyoku import (
    HermesBridgeEnvelope,
    HermesBridgeError,
    ModelEndpoint,
    dry_run_hermes_bridge,
    load_hermes_bridge_envelope,
)


def local_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="local-echo",
        provider="local",
        privacy_level="local",
        context_window_tokens=4096,
        average_latency_ms=10,
        invocation=(sys.executable, "-c", "print('ready')"),
        capabilities={"conversation": 0.95, "instruction_following": 0.9},
    )


def cli_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="cli-fallback",
        provider="cli",
        privacy_level="remote",
        context_window_tokens=128000,
        average_latency_ms=20,
        invocation=("missing-cli-command",),
        capabilities={"conversation": 0.9, "instruction_following": 0.9},
    )


def envelope_payload() -> dict:
    return {
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
        "prompt": "Confirm the dry-run bridge.",
        "routing": {
            "checkHealth": True,
            "fallback": True,
            "maxAttempts": 2,
        },
    }


class HermesBridgeTests(unittest.TestCase):
    def test_loads_one_symbiote_envelope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "envelope.json"
            path.write_text(json.dumps(envelope_payload()), encoding="utf-8")

            envelope = load_hermes_bridge_envelope(path)

        self.assertEqual(envelope.symbiote_id, "symbiote-01")
        self.assertEqual(envelope.role, "primary")
        self.assertEqual(envelope.task.task_id, "hermes.bridge.one-symbiote")
        self.assertEqual(envelope.execution_key, "symbiote-01:primary:hermes.bridge.one-symbiote")
        self.assertTrue(envelope.routing.check_health)
        self.assertEqual(envelope.routing.max_attempts, 2)

    def test_rejects_multi_symbiote_payload(self):
        payload = envelope_payload()
        payload["symbiotes"] = [{"symbioteId": "symbiote-01"}, {"symbioteId": "symbiote-02"}]

        with self.assertRaises(HermesBridgeError) as error:
            HermesBridgeEnvelope.from_dict(payload)

        self.assertIn("exactly one Symbiote", str(error.exception))

    def test_dry_run_selects_model_and_does_not_start_execution(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())

        result = dry_run_hermes_bridge(
            [local_endpoint(), cli_endpoint()],
            envelope,
            command_resolver=lambda command: command if command == sys.executable else None,
        )
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["selectedModel"]["modelId"], "local-echo")
        self.assertEqual(payload["handoff"]["status"], "dry-run-ready")
        self.assertEqual(payload["execution"]["status"], "not-started")
        self.assertFalse(payload["execution"]["started"])
        self.assertEqual(payload["duplicateGuard"]["executionKey"], envelope.execution_key)
        self.assertTrue(any(item["modelId"] == "local-echo" and item["ready"] for item in payload["readiness"]))

    def test_dry_run_prevents_duplicate_execution_key(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())

        result = dry_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            seen_execution_keys=[envelope.execution_key],
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "duplicate-prevented")
        self.assertEqual(payload["execution"]["status"], "skipped")
        self.assertTrue(payload["duplicateGuard"]["duplicate"])
        self.assertEqual(payload["error"]["code"], "duplicate_execution_key")

    def test_dry_run_reports_recoverable_routing_blocker(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        weak_model = ModelEndpoint(
            model_id="weak-local",
            provider="local",
            privacy_level="local",
            context_window_tokens=4096,
            average_latency_ms=10,
            invocation=(sys.executable,),
            capabilities={"conversation": 0.2},
        )

        result = dry_run_hermes_bridge([weak_model], envelope)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "routing-blocked")
        self.assertEqual(payload["error"]["code"], "no_eligible_model")
        self.assertIn("instruction_following", payload["error"]["message"])


class HermesBridgeCliTests(unittest.TestCase):
    def test_cli_dry_run_outputs_bridge_report(self):
        from furyoku.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "envelope.json"
            registry_path.write_text(
                json.dumps(
                    {
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
                                    "import sys; print(sys.stdin.read())",
                                ],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(envelope_payload()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "furyoku.cli",
                    "hermes-bridge",
                    "--registry",
                    str(registry_path),
                    "--envelope",
                    str(envelope_path),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["bridge"], "hermes-furyoku")
        self.assertEqual(payload["selectedModel"]["modelId"], "local-echo")
        self.assertEqual(payload["handoff"]["status"], "dry-run-ready")

    def test_cli_requires_dry_run_flag(self):
        from furyoku.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "envelope.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [sys.executable],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(envelope_payload()), encoding="utf-8")

            with redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(
                        [
                            "hermes-bridge",
                            "--registry",
                            str(registry_path),
                            "--envelope",
                            str(envelope_path),
                        ]
                    )

        self.assertEqual(error.exception.code, 2)
