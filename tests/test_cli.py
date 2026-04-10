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
                    "speed": 0.96,
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
                    "reasoning": 0.96,
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_executable_character_registry(path: Path) -> None:
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
                    "speed": 0.96,
                },
            },
            {
                "modelId": "cli-coder",
                "provider": "cli",
                "privacyLevel": "remote",
                "contextWindowTokens": 128000,
                "averageLatencyMs": 20,
                "invocation": [
                    sys.executable,
                    "-c",
                    "import sys; print('code:' + sys.stdin.read())",
                ],
                "supportsTools": True,
                "capabilities": {
                    "conversation": 0.8,
                    "instruction_following": 0.9,
                    "coding": 0.98,
                    "reasoning": 0.96,
                },
            },
            {
                "modelId": "api-memory",
                "provider": "api",
                "privacyLevel": "remote",
                "contextWindowTokens": 200000,
                "averageLatencyMs": 100,
                "inputCostPer1k": 0.004,
                "outputCostPer1k": 0.012,
                "supportsJson": True,
                "capabilities": {
                    "conversation": 0.8,
                    "instruction_following": 0.86,
                    "retrieval": 0.95,
                    "summarization": 0.94,
                    "speed": 0.78,
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_task_profile(path: Path) -> None:
    payload = {
        "schemaVersion": 1,
        "taskId": "private-chat",
        "privacyRequirement": "local_only",
        "requiredCapabilities": {"conversation": 0.9},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_decision_suite(path: Path) -> None:
    payload = {
        "schemaVersion": 1,
        "suiteId": "test-suite",
        "situations": [
            {
                "taskId": "private-chat",
                "privacyRequirement": "local_only",
                "requiredCapabilities": {"conversation": 0.9},
            },
            {
                "taskId": "coding",
                "requireTools": True,
                "requiredCapabilities": {"coding": 0.9, "reasoning": 0.85},
            },
            {
                "taskId": "memory",
                "minContextTokens": 64000,
                "requireJson": True,
                "requiredCapabilities": {"retrieval": 0.9, "summarization": 0.9},
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_character_profile(path: Path) -> None:
    payload = {
        "schemaVersion": 1,
        "characterId": "test-character",
        "class": "Symbiote",
        "rank": "Prototype",
        "roles": [
            {
                "roleId": "primary",
                "primary": True,
                "maxSubagents": 2,
                "task": {
                    "taskId": "test-character.primary",
                    "privacyRequirement": "local_only",
                    "requiredCapabilities": {"conversation": 0.9},
                },
            },
            {
                "roleId": "coding",
                "maxSubagents": 4,
                "task": {
                    "taskId": "test-character.coding",
                    "requireTools": True,
                    "requiredCapabilities": {"coding": 0.9, "instruction_following": 0.8},
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_local_only_registry(path: Path) -> None:
    payload = {
        "schemaVersion": 1,
        "models": [
            {
                "modelId": "python-local",
                "provider": "local",
                "privacyLevel": "local",
                "contextWindowTokens": 4096,
                "averageLatencyMs": 10,
                "invocation": [sys.executable, "-c", "print('ready')"],
                "capabilities": {"conversation": 0.9},
            }
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

    def test_select_accepts_task_profile_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            task_path = Path(temp_dir) / "task.json"
            write_registry(registry_path)
            write_task_profile(task_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "select",
                        "--registry",
                        str(registry_path),
                        "--task-profile",
                        str(task_path),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["modelId"], "local-echo")

    def test_health_reports_registry_provider_readiness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            write_local_only_registry(registry_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["health", "--registry", str(registry_path)])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["providers"][0]["modelId"], "python-local")
            self.assertEqual(payload["providers"][0]["status"], "ready")

    def test_decide_outputs_multi_situation_decision_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            write_executable_character_registry(registry_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["decide", "--registry", str(registry_path)])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertGreaterEqual(len(payload["decisions"]), 3)
            selected_by_task = {
                decision["taskId"]: decision["selectedModel"]["modelId"]
                for decision in payload["decisions"]
                if decision["selectedModel"]
            }
            self.assertEqual(selected_by_task["decision.private-chat"], "local-echo")
            self.assertEqual(selected_by_task["decision.tool-heavy-coding"], "cli-coder")
            self.assertGreaterEqual(len(payload["summaries"]), 2)
            coding_decision = next(
                decision for decision in payload["decisions"] if decision["taskId"] == "decision.tool-heavy-coding"
            )
            local_rank = next(
                score for score in coding_decision["rankedModels"] if score["modelId"] == "local-echo"
            )
            self.assertFalse(local_rank["eligible"])
            self.assertTrue(any("tool support" in blocker for blocker in local_rank["blockers"]))

    def test_decide_accepts_explicit_task_profile_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            task_path = Path(temp_dir) / "task.json"
            write_registry(registry_path)
            write_task_profile(task_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "decide",
                        "--registry",
                        str(registry_path),
                        "--task-profile",
                        str(task_path),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(payload["decisions"]), 1)
            self.assertEqual(payload["decisions"][0]["taskId"], "private-chat")
            self.assertEqual(payload["decisions"][0]["selectedModel"]["modelId"], "local-echo")

    def test_decide_accepts_decision_suite_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            suite_path = Path(temp_dir) / "suite.json"
            write_executable_character_registry(registry_path)
            write_decision_suite(suite_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "decide",
                        "--registry",
                        str(registry_path),
                        "--decision-suite",
                        str(suite_path),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual([decision["taskId"] for decision in payload["decisions"]], ["private-chat", "coding", "memory"])
            self.assertEqual(payload["decisions"][0]["selectedModel"]["modelId"], "local-echo")
            self.assertEqual(payload["decisions"][1]["selectedModel"]["modelId"], "cli-coder")
            self.assertEqual(payload["decisions"][2]["selectedModel"]["modelId"], "api-memory")

    def test_decide_check_health_demotes_not_ready_endpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            suite_path = Path(temp_dir) / "suite.json"
            write_executable_character_registry(registry_path)
            write_decision_suite(suite_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "decide",
                        "--registry",
                        str(registry_path),
                        "--decision-suite",
                        str(suite_path),
                        "--check-health",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["blockedTasks"], ["memory"])
            readiness_by_model = {result["modelId"]: result for result in payload["readiness"]}
            self.assertEqual(readiness_by_model["local-echo"]["status"], "ready")
            self.assertEqual(readiness_by_model["api-memory"]["status"], "missing-transport")
            memory_decision = next(decision for decision in payload["decisions"] if decision["taskId"] == "memory")
            api_rank = next(score for score in memory_decision["rankedModels"] if score["modelId"] == "api-memory")
            self.assertFalse(api_rank["eligible"])
            self.assertTrue(any("provider readiness" in blocker for blocker in api_rank["blockers"]))

    def test_character_select_outputs_role_to_model_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            character_path = Path(temp_dir) / "character.json"
            write_registry(registry_path)
            write_character_profile(character_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "character-select",
                        "--registry",
                        str(registry_path),
                        "--character-profile",
                        str(character_path),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["characterId"], "test-character")
            self.assertEqual(payload["primaryRole"], "primary")
            self.assertEqual(payload["roles"][0]["roleId"], "primary")
            self.assertEqual(payload["roles"][0]["selection"]["modelId"], "local-echo")
            self.assertEqual(payload["roles"][1]["roleId"], "coding")
            self.assertEqual(payload["roles"][1]["maxSubagents"], 4)
            self.assertEqual(payload["roles"][1]["selection"]["modelId"], "remote-coder")

    def test_character_run_executes_effective_primary_role(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            character_path = Path(temp_dir) / "character.json"
            write_executable_character_registry(registry_path)
            write_character_profile(character_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "character-run",
                        "--registry",
                        str(registry_path),
                        "--character-profile",
                        str(character_path),
                        "--prompt",
                        "hello",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["characterId"], "test-character")
            self.assertEqual(payload["executedRoleId"], "primary")
            self.assertEqual(payload["selectedModel"]["modelId"], "local-echo")
            self.assertEqual(payload["execution"]["responseText"].strip(), "echo:hello")
            self.assertEqual(payload["roleAssignments"]["primaryRole"], "primary")
            self.assertEqual(payload["roleAssignments"]["roles"][1]["roleId"], "coding")
            self.assertEqual(payload["roleAssignments"]["roles"][1]["maxSubagents"], 4)

    def test_character_run_executes_named_secondary_role(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            character_path = Path(temp_dir) / "character.json"
            write_executable_character_registry(registry_path)
            write_character_profile(character_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "character-run",
                        "--registry",
                        str(registry_path),
                        "--character-profile",
                        str(character_path),
                        "--role-id",
                        "coding",
                        "--prompt",
                        "write code",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["characterId"], "test-character")
            self.assertEqual(payload["executedRoleId"], "coding")
            self.assertEqual(payload["selectedModel"]["modelId"], "cli-coder")
            self.assertEqual(payload["selectedModel"]["provider"], "cli")
            self.assertEqual(payload["execution"]["responseText"].strip(), "code:write code")
            self.assertEqual(payload["roleAssignments"]["roles"][0]["selection"]["modelId"], "local-echo")

    def test_character_run_returns_stable_json_for_execution_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            character_path = Path(temp_dir) / "character.json"
            write_registry(registry_path)
            write_character_profile(character_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "character-run",
                        "--registry",
                        str(registry_path),
                        "--character-profile",
                        str(character_path),
                        "--role-id",
                        "coding",
                        "--prompt",
                        "write code",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["executedRoleId"], "coding")
            self.assertEqual(payload["selectedModel"]["modelId"], "remote-coder")
            self.assertEqual(payload["execution"]["status"], "error")
            self.assertIn("api transport", payload["execution"]["error"])
            self.assertEqual(payload["roleAssignments"]["roles"][1]["selection"]["modelId"], "remote-coder")


if __name__ == "__main__":
    unittest.main()
