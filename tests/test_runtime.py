import subprocess
import unittest

from furyoku import (
    DecisionOutcomeRecord,
    ModelDecisionError,
    ModelEndpoint,
    ProviderExecutionRequest,
    RouterError,
    SubprocessProviderAdapter,
    TaskProfile,
    execute_decision_situation,
    execute_character_role,
    parse_decision_suite,
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

    def test_execute_decision_situation_runs_named_suite_task(self):
        suite = parse_decision_suite(
            {
                "schemaVersion": 1,
                "suiteId": "runtime-suite",
                "situations": [
                    {
                        "taskId": "private-chat",
                        "privacyRequirement": "local_only",
                        "weight": 3.0,
                        "minimumScore": 90.0,
                        "requiredCapabilities": {"conversation": 0.9},
                    }
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_decision_situation(
            [local_endpoint(), cli_endpoint()],
            suite,
            "private-chat",
            "hello",
            adapters={"local": SubprocessProviderAdapter(runner)},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.model_id, "local-chat")
        self.assertEqual(result.decision.weight, 3.0)
        self.assertEqual(result.execution.response_text, "local-chat:hello")

    def test_execute_decision_situation_uses_feedback_informed_selection(self):
        suite = parse_decision_suite(
            {
                "schemaVersion": 1,
                "suiteId": "feedback-suite",
                "situations": [
                    {
                        "taskId": "feedback-chat",
                        "requiredCapabilities": {"conversation": 0.8},
                    }
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_decision_situation(
            [local_endpoint(), cli_endpoint()],
            suite,
            "feedback-chat",
            "hello",
            feedback=[
                DecisionOutcomeRecord(
                    record_id="feedback-1",
                    report_path="decision-report.json",
                    report_sha256="0" * 64,
                    generated_at="2026-04-10T12:00:00+00:00",
                    selected_model_id="local-chat",
                    selected_provider="local",
                    verdict="success",
                    score=1.0,
                )
            ],
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.model_id, "local-chat")
        self.assertIn("local-chat", result.report.feedback_adjustments)
        self.assertTrue(any("outcome feedback adjustment" in reason for reason in result.selection.reasons))
        self.assertEqual(result.execution.response_text, "local-chat:hello")

    def test_execute_decision_situation_does_not_execute_threshold_blocked_task(self):
        suite = parse_decision_suite(
            {
                "schemaVersion": 1,
                "suiteId": "blocked-suite",
                "situations": [
                    {
                        "taskId": "too-strict",
                        "minimumScore": 120.0,
                        "requiredCapabilities": {"conversation": 0.5},
                    }
                ],
            }
        )

        result = execute_decision_situation([local_endpoint()], suite, "too-strict", "hello")

        self.assertFalse(result.ok)
        self.assertIsNone(result.selection)
        self.assertIsNone(result.execution)
        self.assertTrue(
            any("below minimum score 120.00" in blocker for blocker in result.decision.blockers["local-chat"])
        )

    def test_execute_decision_situation_rejects_unknown_situation(self):
        suite = parse_decision_suite(
            {
                "schemaVersion": 1,
                "suiteId": "runtime-suite",
                "situations": [{"taskId": "known", "requiredCapabilities": {"conversation": 0.5}}],
            }
        )

        with self.assertRaises(ModelDecisionError) as error:
            execute_decision_situation([local_endpoint()], suite, "missing", "hello")

        self.assertIn("Unknown decision situation", str(error.exception))

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
