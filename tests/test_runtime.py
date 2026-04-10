import subprocess
import unittest

from furyoku import (
    ModelEndpoint,
    ProviderExecutionRequest,
    RouterError,
    SubprocessProviderAdapter,
    TaskProfile,
    execute_character_role,
    parse_character_profile,
    route_and_execute,
)


def local_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="local-chat",
        provider="local",
        privacy_level="local",
        context_window_tokens=4096,
        average_latency_ms=10,
        invocation=("local-chat",),
        capabilities={"conversation": 0.95, "instruction_following": 0.9},
    )


def cli_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="cli-coder",
        provider="cli",
        privacy_level="remote",
        context_window_tokens=128000,
        average_latency_ms=20,
        invocation=("cli-coder",),
        capabilities={"conversation": 0.8, "instruction_following": 0.85, "coding": 0.95},
        supports_tools=True,
    )


class RuntimeTests(unittest.TestCase):
    def test_route_and_execute_returns_selection_and_execution_result(self):
        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = route_and_execute(
            [local_endpoint(), cli_endpoint()],
            TaskProfile(
                task_id="private-chat",
                required_capabilities={"conversation": 0.9},
                privacy_requirement="local_only",
            ),
            "hello",
            adapters={"local": SubprocessProviderAdapter(runner)},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.model_id, "local-chat")
        self.assertEqual(result.provider, "local")
        self.assertEqual(result.execution.response_text, "local-chat:hello")
        self.assertGreater(result.selection.score, 0)

    def test_route_and_execute_preserves_execution_failure_observability(self):
        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 3, stdout="", stderr="bad runtime")

        result = route_and_execute(
            [local_endpoint()],
            TaskProfile(task_id="chat", required_capabilities={"conversation": 0.9}),
            ProviderExecutionRequest("hello", timeout_seconds=2),
            adapters={"local": SubprocessProviderAdapter(runner)},
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.selection.eligible)
        self.assertEqual(result.execution.status, "error")
        self.assertEqual(result.execution.stderr, "bad runtime")

    def test_execute_character_role_defaults_to_primary_role(self):
        profile = parse_character_profile(
            {
                "schemaVersion": 1,
                "characterId": "test-symbiote",
                "roles": [
                    {
                        "roleId": "primary",
                        "primary": True,
                        "task": {
                            "taskId": "test-symbiote.primary",
                            "privacyRequirement": "local_only",
                            "requiredCapabilities": {"conversation": 0.9},
                        },
                    },
                    {
                        "roleId": "coding",
                        "task": {
                            "taskId": "test-symbiote.coding",
                            "requireTools": True,
                            "requiredCapabilities": {"coding": 0.9},
                        },
                    },
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_character_role(
            [local_endpoint(), cli_endpoint()],
            profile,
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.character_id, "test-symbiote")
        self.assertEqual(result.role_id, "primary")
        self.assertEqual(result.model_id, "local-chat")
        self.assertEqual(result.execution.response_text, "local-chat:hello")
        self.assertIn("coding", result.character_selection.roles)

    def test_execute_character_role_can_execute_named_secondary_role(self):
        profile = parse_character_profile(
            {
                "schemaVersion": 1,
                "characterId": "test-symbiote",
                "roles": [
                    {
                        "roleId": "primary",
                        "primary": True,
                        "task": {
                            "taskId": "test-symbiote.primary",
                            "privacyRequirement": "local_only",
                            "requiredCapabilities": {"conversation": 0.9},
                        },
                    },
                    {
                        "roleId": "coding",
                        "maxSubagents": 4,
                        "task": {
                            "taskId": "test-symbiote.coding",
                            "requireTools": True,
                            "requiredCapabilities": {"coding": 0.9},
                        },
                    },
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_character_role(
            [local_endpoint(), cli_endpoint()],
            profile,
            ProviderExecutionRequest("write code", timeout_seconds=2),
            role_id="coding",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.role_id, "coding")
        self.assertEqual(result.model_id, "cli-coder")
        self.assertEqual(result.provider, "cli")
        self.assertEqual(result.character_selection.max_subagents_for("coding"), 4)
        self.assertEqual(result.execution.response_text, "cli-coder:write code")

    def test_execute_character_role_rejects_unknown_role(self):
        profile = parse_character_profile(
            {
                "schemaVersion": 1,
                "characterId": "test-symbiote",
                "roles": [
                    {
                        "roleId": "primary",
                        "primary": True,
                        "task": {
                            "taskId": "test-symbiote.primary",
                            "requiredCapabilities": {"conversation": 0.9},
                        },
                    }
                ],
            }
        )

        with self.assertRaises(RouterError) as error:
            execute_character_role([local_endpoint()], profile, "hello", role_id="missing")

        self.assertIn("Unknown CHARACTER role", str(error.exception))


if __name__ == "__main__":
    unittest.main()
