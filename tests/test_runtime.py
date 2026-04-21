import subprocess
import unittest

from furyoku import (
    CharacterArrayError,
    DecisionOutcomeRecord,
    ModelDecisionError,
    ModelEndpoint,
    ProviderExecutionRequest,
    ProviderHealthCheckResult,
    RouterError,
    RoutingScorePolicy,
    SubprocessProviderAdapter,
    TaskProfile,
    compare_decision_suite_executions,
    compare_decision_situation_executions,
    compare_model_executions,
    execute_character_array,
    execute_character_array_member,
    execute_decision_situation,
    execute_decision_situation_with_fallback,
    execute_character_role,
    parse_character_array,
    parse_decision_suite,
    parse_character_profile,
    route_and_execute,
    route_and_execute_with_fallback,
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

    def test_route_and_execute_uses_feedback_informed_selection(self):
        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = route_and_execute(
            [local_endpoint(), cli_endpoint()],
            TaskProfile(task_id="feedback-chat", required_capabilities={"conversation": 0.8}),
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
        self.assertIsNotNone(result.report)
        self.assertIn("local-chat", result.report.feedback_adjustments)
        self.assertEqual(result.execution.response_text, "local-chat:hello")

    def test_route_and_execute_uses_readiness_informed_selection(self):
        local = ModelEndpoint(
            model_id="local-fallback",
            provider="local",
            privacy_level="local",
            context_window_tokens=4096,
            average_latency_ms=20000,
            invocation=("local-fallback",),
            capabilities={"conversation": 0.9},
        )
        cli = ModelEndpoint(
            model_id="cli-primary",
            provider="cli",
            privacy_level="remote",
            context_window_tokens=128000,
            average_latency_ms=10,
            invocation=("missing-cli",),
            capabilities={"conversation": 1.0},
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = route_and_execute(
            [local, cli],
            TaskProfile(task_id="readiness-chat", required_capabilities={"conversation": 0.8}),
            "hello",
            readiness=[
                ProviderHealthCheckResult(
                    model_id="cli-primary",
                    provider="cli",
                    status="missing-command",
                    ready=False,
                    reason="command 'missing-cli' was not found",
                    command="missing-cli",
                ),
                ProviderHealthCheckResult(
                    model_id="local-fallback",
                    provider="local",
                    status="ready",
                    ready=True,
                    reason="command is available",
                    command="local-fallback",
                ),
            ],
            adapters={"local": SubprocessProviderAdapter(runner)},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.model_id, "local-fallback")
        self.assertIsNotNone(result.report)
        self.assertIn("cli-primary", result.report.situations["readiness-chat"].blockers)
        self.assertEqual(result.execution.response_text, "local-fallback:hello")

    def test_route_and_execute_uses_routing_policy(self):
        fast_local = ModelEndpoint(
            model_id="fast-local",
            provider="local",
            privacy_level="local",
            context_window_tokens=4096,
            average_latency_ms=100,
            invocation=("fast-local",),
            capabilities={"conversation": 0.82},
        )
        slow_api = ModelEndpoint(
            model_id="slow-api",
            provider="api",
            privacy_level="remote",
            context_window_tokens=4096,
            average_latency_ms=29000,
            capabilities={"conversation": 0.95},
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = route_and_execute(
            [fast_local, slow_api],
            TaskProfile(task_id="policy-chat", required_capabilities={"conversation": 0.8}),
            "hello",
            routing_policy=RoutingScorePolicy(capability_weight=40.0, speed_bonus_weight=80.0),
            adapters={"local": SubprocessProviderAdapter(runner)},
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.model_id, "fast-local")
        self.assertIsNotNone(result.report.routing_policy_metadata)
        self.assertEqual(result.execution.response_text, "fast-local:hello")

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

    def test_route_and_execute_with_fallback_tries_next_eligible_model_after_failure(self):
        def runner(invocation, prompt, timeout):
            if invocation[0] == "local-chat":
                return subprocess.CompletedProcess(invocation, 3, stdout="", stderr="local failed")
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = route_and_execute_with_fallback(
            [local_endpoint(), cli_endpoint()],
            TaskProfile(
                task_id="fallback-chat",
                privacy_requirement="prefer_local",
                required_capabilities={"conversation": 0.8},
            ),
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.model_id, "cli-coder")
        self.assertEqual(len(result.execution_attempts), 2)
        self.assertEqual(result.execution_attempts[0].selection.model.model_id, "local-chat")
        self.assertEqual(result.execution_attempts[0].execution.status, "error")
        self.assertEqual(result.execution_attempts[1].selection.model.model_id, "cli-coder")
        self.assertEqual(result.execution.response_text, "cli-coder:hello")

    def test_route_and_execute_with_fallback_never_tries_blocked_models(self):
        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 3, stdout="", stderr="runtime failed")

        result = route_and_execute_with_fallback(
            [local_endpoint(), cli_endpoint()],
            TaskProfile(
                task_id="private-chat",
                privacy_requirement="local_only",
                required_capabilities={"conversation": 0.8},
            ),
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.model_id, "local-chat")
        self.assertEqual(len(result.execution_attempts), 1)
        self.assertEqual(result.execution_attempts[0].selection.model.model_id, "local-chat")
        self.assertIn("cli-coder", result.report.situations["private-chat"].blockers)

    def test_route_and_execute_with_fallback_respects_max_attempts(self):
        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 3, stdout="", stderr="runtime failed")

        result = route_and_execute_with_fallback(
            [local_endpoint(), cli_endpoint()],
            TaskProfile(
                task_id="fallback-chat",
                privacy_requirement="prefer_local",
                required_capabilities={"conversation": 0.8},
            ),
            "hello",
            max_attempts=1,
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.model_id, "local-chat")
        self.assertEqual(len(result.execution_attempts), 1)

    def test_compare_model_executions_runs_all_eligible_models(self):
        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = compare_model_executions(
            [local_endpoint(), cli_endpoint()],
            TaskProfile(
                task_id="compare-chat",
                privacy_requirement="prefer_local",
                required_capabilities={"conversation": 0.8},
            ),
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.executed_count, 2)
        self.assertEqual(result.successful_count, 2)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.execution_attempts[0].selection.model.model_id, "local-chat")
        self.assertEqual(result.execution_attempts[1].selection.model.model_id, "cli-coder")
        self.assertEqual(result.execution_attempts[1].execution.response_text, "cli-coder:hello")

    def test_compare_model_executions_preserves_partial_failure(self):
        def runner(invocation, prompt, timeout):
            if invocation[0] == "local-chat":
                return subprocess.CompletedProcess(invocation, 3, stdout="", stderr="local failed")
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = compare_model_executions(
            [local_endpoint(), cli_endpoint()],
            TaskProfile(
                task_id="compare-chat",
                privacy_requirement="prefer_local",
                required_capabilities={"conversation": 0.8},
            ),
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.executed_count, 2)
        self.assertEqual(result.successful_count, 1)
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.execution_attempts[0].execution.status, "error")
        self.assertEqual(result.execution_attempts[1].execution.status, "ok")

    def test_compare_model_executions_respects_max_candidates(self):
        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = compare_model_executions(
            [local_endpoint(), cli_endpoint()],
            TaskProfile(
                task_id="compare-chat",
                privacy_requirement="prefer_local",
                required_capabilities={"conversation": 0.8},
            ),
            "hello",
            max_candidates=1,
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.max_candidates, 1)
        self.assertEqual(result.executed_count, 1)
        self.assertEqual(result.execution_attempts[0].selection.model.model_id, "local-chat")

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

    def test_execute_decision_situation_with_fallback_tries_next_eligible_model(self):
        suite = parse_decision_suite(
            {
                "schemaVersion": 1,
                "suiteId": "fallback-suite",
                "situations": [
                    {
                        "taskId": "fallback-chat",
                        "privacyRequirement": "prefer_local",
                        "requiredCapabilities": {"conversation": 0.8},
                    }
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            if invocation[0] == "local-chat":
                return subprocess.CompletedProcess(invocation, 3, stdout="", stderr="local failed")
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_decision_situation_with_fallback(
            [local_endpoint(), cli_endpoint()],
            suite,
            "fallback-chat",
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.model_id, "cli-coder")
        self.assertEqual(result.situation_id, "fallback-chat")
        self.assertEqual(len(result.execution_attempts), 2)
        self.assertEqual(result.execution_attempts[0].selection.model.model_id, "local-chat")
        self.assertEqual(result.execution_attempts[1].selection.model.model_id, "cli-coder")

    def test_compare_decision_situation_executions_runs_suite_candidates(self):
        suite = parse_decision_suite(
            {
                "schemaVersion": 1,
                "suiteId": "compare-suite",
                "situations": [
                    {
                        "taskId": "compare-chat",
                        "privacyRequirement": "prefer_local",
                        "requiredCapabilities": {"conversation": 0.8},
                    }
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = compare_decision_situation_executions(
            [local_endpoint(), cli_endpoint()],
            suite,
            "compare-chat",
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.situation_id, "compare-chat")
        self.assertEqual(result.executed_count, 2)
        self.assertEqual(result.execution_attempts[0].selection.model.model_id, "local-chat")
        self.assertEqual(result.execution_attempts[1].selection.model.model_id, "cli-coder")

    def test_compare_decision_suite_executions_runs_all_suite_situations(self):
        suite = parse_decision_suite(
            {
                "schemaVersion": 1,
                "suiteId": "batch-suite",
                "situations": [
                    {
                        "taskId": "fallback-chat",
                        "privacyRequirement": "prefer_local",
                        "requiredCapabilities": {"conversation": 0.8},
                    },
                    {
                        "taskId": "tool-heavy-coding",
                        "requireTools": True,
                        "requiredCapabilities": {"coding": 0.9},
                    },
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            if invocation[0] == "local-chat":
                return subprocess.CompletedProcess(invocation, 3, stdout="", stderr="local failed")
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = compare_decision_suite_executions(
            [local_endpoint(), cli_endpoint()],
            suite,
            {
                "fallback-chat": "hello",
                "tool-heavy-coding": ProviderExecutionRequest("write code", timeout_seconds=2),
            },
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.suite_id, "batch-suite")
        self.assertEqual(len(result.situation_results), 2)
        self.assertEqual(result.successful_situation_count, 2)
        self.assertEqual(result.blocked_situation_count, 0)
        self.assertEqual(result.executed_candidate_count, 3)
        self.assertEqual(result.successful_execution_count, 2)
        self.assertEqual(result.failed_execution_count, 1)
        self.assertEqual(result.situation_results[0].execution_attempts[0].selection.model.model_id, "local-chat")
        self.assertEqual(result.situation_results[1].execution_attempts[0].selection.model.model_id, "cli-coder")

    def test_compare_decision_suite_executions_surfaces_blocked_situations(self):
        suite = parse_decision_suite(
            {
                "schemaVersion": 1,
                "suiteId": "blocked-batch-suite",
                "situations": [
                    {
                        "taskId": "fallback-chat",
                        "privacyRequirement": "prefer_local",
                        "requiredCapabilities": {"conversation": 0.8},
                    },
                    {
                        "taskId": "too-strict",
                        "minimumScore": 120.0,
                        "requiredCapabilities": {"conversation": 0.5},
                    },
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = compare_decision_suite_executions(
            [local_endpoint(), cli_endpoint()],
            suite,
            {
                "fallback-chat": "hello",
                "too-strict": "blocked prompt",
            },
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.blocked_situation_count, 1)
        self.assertEqual(result.successful_situation_count, 1)
        self.assertEqual(result.report.blocked_tasks, ("too-strict",))
        self.assertEqual(result.situation_results[1].executed_count, 0)

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

    def test_execute_character_array_member_defaults_to_primary_slot_and_role(self):
        array = parse_character_array(
            {
                "schemaVersion": 1,
                "arrayId": "runtime-aca",
                "members": [
                    {
                        "alias": "lead",
                        "primary": True,
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "lead-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "lead-character.primary",
                                        "privacyRequirement": "local_only",
                                        "requiredCapabilities": {"conversation": 0.9},
                                    },
                                },
                                {
                                    "roleId": "coding",
                                    "task": {
                                        "taskId": "lead-character.coding",
                                        "requireTools": True,
                                        "requiredCapabilities": {"coding": 0.9},
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "alias": "support",
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "support-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "support-character.primary",
                                        "requireTools": True,
                                        "requiredCapabilities": {"coding": 0.9},
                                    },
                                }
                            ],
                        },
                    },
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_character_array_member(
            [local_endpoint(), cli_endpoint()],
            array,
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.array_id, "runtime-aca")
        self.assertEqual(result.slot_id, "lead")
        self.assertTrue(result.primary)
        self.assertEqual(result.character_id, "lead-character")
        self.assertEqual(result.role_id, "primary")
        self.assertEqual(result.model_id, "local-chat")
        self.assertEqual(result.execution.response_text, "local-chat:hello")

    def test_execute_character_array_member_selects_named_slot_and_role(self):
        array = parse_character_array(
            {
                "schemaVersion": 1,
                "arrayId": "runtime-aca-named",
                "members": [
                    {
                        "alias": "lead",
                        "primary": True,
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "lead-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "lead-character.primary",
                                        "privacyRequirement": "local_only",
                                        "requiredCapabilities": {"conversation": 0.9},
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "alias": "support",
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "support-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "support-character.primary",
                                        "requiredCapabilities": {"conversation": 0.5},
                                    },
                                },
                                {
                                    "roleId": "coding",
                                    "maxSubagents": 3,
                                    "task": {
                                        "taskId": "support-character.coding",
                                        "requireTools": True,
                                        "requiredCapabilities": {"coding": 0.9},
                                    },
                                },
                            ],
                        },
                    },
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_character_array_member(
            [local_endpoint(), cli_endpoint()],
            array,
            ProviderExecutionRequest("write code", timeout_seconds=2),
            slot_id="support",
            role_id="coding",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.slot_id, "support")
        self.assertFalse(result.primary)
        self.assertEqual(result.character_id, "support-character")
        self.assertEqual(result.role_id, "coding")
        self.assertEqual(result.model_id, "cli-coder")
        self.assertEqual(result.provider, "cli")
        self.assertEqual(result.execution.response_text, "cli-coder:write code")
        self.assertEqual(result.character_selection.max_subagents_for("coding"), 3)

    def test_execute_character_array_member_rejects_unknown_slot(self):
        array = parse_character_array(
            {
                "schemaVersion": 1,
                "arrayId": "runtime-aca-unknown-slot",
                "members": [
                    {
                        "alias": "solo",
                        "primary": True,
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "solo-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "solo-character.primary",
                                        "requiredCapabilities": {"conversation": 0.5},
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        )

        with self.assertRaises(CharacterArrayError) as error:
            execute_character_array_member([local_endpoint()], array, "hello", slot_id="missing")

        self.assertIn("Unknown CHARACTER ARRAY slot", str(error.exception))

    def test_execute_character_array_fans_out_each_members_primary_role(self):
        array = parse_character_array(
            {
                "schemaVersion": 1,
                "arrayId": "runtime-aca-fanout",
                "members": [
                    {
                        "alias": "lead",
                        "primary": True,
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "lead-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "lead-character.primary",
                                        "privacyRequirement": "local_only",
                                        "requiredCapabilities": {"conversation": 0.9},
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "alias": "support",
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "support-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "support-character.primary",
                                        "requireTools": True,
                                        "requiredCapabilities": {"coding": 0.9},
                                    },
                                }
                            ],
                        },
                    },
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_character_array(
            [local_endpoint(), cli_endpoint()],
            array,
            "hello",
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.array_id, "runtime-aca-fanout")
        self.assertEqual(result.member_count, 2)
        self.assertEqual(result.successful_count, 2)
        self.assertEqual(result.failed_count, 0)
        lead = result.member_result("lead")
        support = result.member_result("support")
        self.assertEqual(lead.role_id, "primary")
        self.assertEqual(lead.model_id, "local-chat")
        self.assertEqual(lead.execution.response_text, "local-chat:hello")
        self.assertEqual(support.role_id, "primary")
        self.assertEqual(support.model_id, "cli-coder")
        self.assertEqual(support.execution.response_text, "cli-coder:hello")

    def test_execute_character_array_applies_per_slot_role_overrides(self):
        array = parse_character_array(
            {
                "schemaVersion": 1,
                "arrayId": "runtime-aca-overrides",
                "members": [
                    {
                        "alias": "lead",
                        "primary": True,
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "lead-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "lead-character.primary",
                                        "privacyRequirement": "local_only",
                                        "requiredCapabilities": {"conversation": 0.9},
                                    },
                                },
                                {
                                    "roleId": "coding",
                                    "task": {
                                        "taskId": "lead-character.coding",
                                        "requireTools": True,
                                        "requiredCapabilities": {"coding": 0.9},
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "alias": "support",
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "support-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "support-character.primary",
                                        "requiredCapabilities": {"conversation": 0.5},
                                    },
                                }
                            ],
                        },
                    },
                ],
            }
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"{invocation[0]}:{prompt}", stderr="")

        result = execute_character_array(
            [local_endpoint(), cli_endpoint()],
            array,
            "hello",
            role_id_by_slot={"lead": "coding"},
            adapters={
                "local": SubprocessProviderAdapter(runner),
                "cli": SubprocessProviderAdapter(runner),
            },
        )

        self.assertTrue(result.ok)
        lead = result.member_result("lead")
        support = result.member_result("support")
        self.assertEqual(lead.role_id, "coding")
        self.assertEqual(lead.model_id, "cli-coder")
        self.assertEqual(lead.execution.response_text, "cli-coder:hello")
        self.assertEqual(support.role_id, "primary")
        self.assertTrue(support.ok)
        self.assertEqual(
            support.execution.response_text,
            f"{support.model_id}:hello",
        )

    def test_execute_character_array_rejects_unknown_slot_override(self):
        array = parse_character_array(
            {
                "schemaVersion": 1,
                "arrayId": "runtime-aca-bad-override",
                "members": [
                    {
                        "alias": "solo",
                        "primary": True,
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "solo-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "solo-character.primary",
                                        "requiredCapabilities": {"conversation": 0.5},
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        )

        with self.assertRaises(CharacterArrayError) as error:
            execute_character_array(
                [local_endpoint()],
                array,
                "hello",
                role_id_by_slot={"missing": "primary"},
            )

        self.assertIn("missing", str(error.exception))

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
