import json
import tempfile
import unittest
from pathlib import Path

from furyoku import (
    DecisionOutcomeRecord,
    FeedbackAdjustmentPolicy,
    ModelDecisionError,
    ModelEndpoint,
    ModelReadinessEvidence,
    ProviderHealthCheckResult,
    TaskProfile,
    evaluate_model_decisions,
    load_decision_suite,
    parse_decision_suite,
)


def sample_models():
    return [
        ModelEndpoint(
            model_id="local-gemma3-heretic",
            provider="local",
            privacy_level="local",
            context_window_tokens=8192,
            average_latency_ms=1500,
            capabilities={
                "conversation": 0.9,
                "instruction_following": 0.85,
                "coding": 0.75,
                "reasoning": 0.82,
                "retrieval": 0.6,
                "summarization": 0.75,
            },
            supports_json=True,
        ),
        ModelEndpoint(
            model_id="cli-codex-high",
            provider="cli",
            privacy_level="remote",
            context_window_tokens=128000,
            average_latency_ms=6000,
            input_cost_per_1k=0.02,
            output_cost_per_1k=0.08,
            capabilities={
                "conversation": 0.85,
                "instruction_following": 0.95,
                "coding": 0.98,
                "reasoning": 0.97,
                "retrieval": 0.8,
                "summarization": 0.87,
            },
            supports_tools=True,
            supports_json=True,
        ),
        ModelEndpoint(
            model_id="api-long-context-memory",
            provider="api",
            privacy_level="remote",
            context_window_tokens=200000,
            average_latency_ms=4000,
            input_cost_per_1k=0.004,
            output_cost_per_1k=0.012,
            capabilities={
                "conversation": 0.8,
                "instruction_following": 0.88,
                "coding": 0.7,
                "reasoning": 0.86,
                "retrieval": 0.97,
                "summarization": 0.95,
            },
            supports_json=True,
        ),
    ]


def sample_tasks():
    return [
        TaskProfile(
            task_id="private-chat",
            required_capabilities={"conversation": 0.8, "instruction_following": 0.8},
            privacy_requirement="local_only",
        ),
        TaskProfile(
            task_id="hard-coding",
            required_capabilities={
                "coding": 0.92,
                "reasoning": 0.9,
                "instruction_following": 0.85,
            },
            require_tools=True,
        ),
        TaskProfile(
            task_id="long-memory",
            required_capabilities={"retrieval": 0.9, "summarization": 0.9},
            min_context_tokens=64000,
            require_json=True,
        ),
    ]


def readiness_models():
    return [
        ModelEndpoint(
            model_id="local-fallback",
            provider="local",
            privacy_level="local",
            context_window_tokens=8192,
            average_latency_ms=800,
            capabilities={"conversation": 0.9, "instruction_following": 0.9},
            invocation=("local-model",),
        ),
        ModelEndpoint(
            model_id="cli-primary",
            provider="cli",
            privacy_level="remote",
            context_window_tokens=128000,
            average_latency_ms=200,
            capabilities={"conversation": 1.0, "instruction_following": 1.0},
            invocation=("missing-cli",),
        ),
        ModelEndpoint(
            model_id="api-primary",
            provider="api",
            privacy_level="remote",
            context_window_tokens=200000,
            average_latency_ms=100,
            capabilities={"conversation": 1.0, "instruction_following": 1.0},
        ),
    ]


def readiness_task():
    return TaskProfile(
        task_id="readiness-chat",
        required_capabilities={"conversation": 0.85, "instruction_following": 0.85},
    )


class ModelDecisionTests(unittest.TestCase):
    def test_evaluate_model_decisions_selects_best_model_per_situation(self):
        report = evaluate_model_decisions(sample_models(), sample_tasks())

        self.assertEqual(report.selected_for("private-chat").model.model_id, "local-gemma3-heretic")
        self.assertEqual(report.selected_for("hard-coding").model.model_id, "cli-codex-high")
        self.assertEqual(report.selected_for("long-memory").model.model_id, "api-long-context-memory")
        self.assertEqual(
            report.aggregate.selected_model_ids,
            ("api-long-context-memory", "cli-codex-high", "local-gemma3-heretic"),
        )
        self.assertEqual(report.aggregate.selected_providers, ("api", "cli", "local"))

    def test_readiness_missing_command_demotes_cli_endpoint(self):
        report = evaluate_model_decisions(
            readiness_models()[:2],
            [readiness_task()],
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
                    command="local-model",
                    resolved_command="C:/tools/local-model.exe",
                ),
            ],
        )

        decision = report.situations["readiness-chat"]

        self.assertEqual(decision.selected.model.model_id, "local-fallback")
        self.assertIn("cli-primary", decision.blockers)
        self.assertTrue(
            any("provider readiness missing-command" in blocker for blocker in decision.blockers["cli-primary"])
        )
        self.assertTrue(any("missing-cli" in blocker for blocker in decision.blockers["cli-primary"]))

    def test_readiness_missing_api_transport_demotes_api_endpoint(self):
        models = [readiness_models()[0], readiness_models()[2]]

        report = evaluate_model_decisions(
            models,
            [readiness_task()],
            readiness=[
                ProviderHealthCheckResult(
                    model_id="api-primary",
                    provider="api",
                    status="missing-transport",
                    ready=False,
                    reason="api health checks require an injected API transport or adapter",
                )
            ],
        )

        decision = report.situations["readiness-chat"]

        self.assertEqual(decision.selected.model.model_id, "local-fallback")
        self.assertIn("api-primary", decision.blockers)
        self.assertTrue(
            any("provider readiness missing-transport" in blocker for blocker in decision.blockers["api-primary"])
        )
        self.assertTrue(any("API transport" in blocker for blocker in decision.blockers["api-primary"]))

    def test_readiness_ready_endpoint_can_still_win(self):
        report = evaluate_model_decisions(
            [readiness_models()[0], readiness_models()[2]],
            [readiness_task()],
            readiness={
                "api-primary": ModelReadinessEvidence(
                    model_id="api-primary",
                    provider="api",
                    status="ready",
                    ready=True,
                    reason="api transport is configured",
                )
            },
        )

        decision = report.situations["readiness-chat"]

        self.assertEqual(decision.selected.model.model_id, "api-primary")
        self.assertTrue(any("provider readiness ready" in reason for reason in decision.selected.reasons))

    def test_feedback_adjustment_can_promote_eligible_model(self):
        task = TaskProfile(
            task_id="feedback-chat",
            required_capabilities={"conversation": 0.8},
        )

        report = evaluate_model_decisions(
            sample_models()[:2],
            [task],
            feedback=[
                DecisionOutcomeRecord(
                    record_id="feedback-1",
                    report_path="decision-report.json",
                    report_sha256="0" * 64,
                    generated_at="2026-04-10T12:00:00+00:00",
                    selected_model_id="local-gemma3-heretic",
                    selected_provider="local",
                    verdict="success",
                    score=1.0,
                )
            ],
        )

        selected = report.selected_for("feedback-chat")
        local_rank = next(score for score in report.situations["feedback-chat"].ranked if score.model.model_id == "local-gemma3-heretic")

        self.assertEqual(selected.model.model_id, "local-gemma3-heretic")
        self.assertIn("local-gemma3-heretic", report.feedback_adjustments)
        self.assertTrue(any("outcome feedback adjustment" in reason for reason in local_rank.reasons))

    def test_feedback_policy_changes_decision_adjustment_size(self):
        task = TaskProfile(
            task_id="feedback-chat",
            required_capabilities={"conversation": 0.8},
        )

        default_report = evaluate_model_decisions(
            sample_models()[:2],
            [task],
            feedback=[
                DecisionOutcomeRecord(
                    record_id="feedback-1",
                    report_path="decision-report.json",
                    report_sha256="0" * 64,
                    generated_at="2026-04-10T12:00:00+00:00",
                    selected_model_id="local-gemma3-heretic",
                    selected_provider="local",
                    verdict="success",
                    score=1.0,
                )
            ],
        )
        policy_report = evaluate_model_decisions(
            sample_models()[:2],
            [task],
            feedback=[
                DecisionOutcomeRecord(
                    record_id="feedback-1",
                    report_path="decision-report.json",
                    report_sha256="0" * 64,
                    generated_at="2026-04-10T12:00:00+00:00",
                    selected_model_id="local-gemma3-heretic",
                    selected_provider="local",
                    verdict="success",
                    score=1.0,
                )
            ],
            feedback_policy=FeedbackAdjustmentPolicy(
                max_adjustment=3.0,
                success_base=0.5,
                success_score_multiplier=1.0,
            ),
        )

        self.assertEqual(default_report.feedback_adjustments["local-gemma3-heretic"].adjustment, 10.0)
        self.assertEqual(policy_report.feedback_adjustments["local-gemma3-heretic"].adjustment, 1.5)

    def test_feedback_adjustment_does_not_bypass_hard_blockers(self):
        task = TaskProfile(
            task_id="feedback-coding",
            required_capabilities={"coding": 0.5},
            require_tools=True,
        )

        report = evaluate_model_decisions(
            sample_models()[:2],
            [task],
            feedback=[
                DecisionOutcomeRecord(
                    record_id="feedback-1",
                    report_path="decision-report.json",
                    report_sha256="0" * 64,
                    generated_at="2026-04-10T12:00:00+00:00",
                    selected_model_id="local-gemma3-heretic",
                    selected_provider="local",
                    verdict="success",
                    score=1.0,
                )
            ],
        )

        local_rank = next(score for score in report.situations["feedback-coding"].ranked if score.model.model_id == "local-gemma3-heretic")

        self.assertFalse(local_rank.eligible)
        self.assertEqual(report.selected_for("feedback-coding").model.model_id, "cli-codex-high")
        self.assertTrue(any("tool support" in blocker for blocker in local_rank.blockers))

    def test_feedback_adjustment_cannot_bypass_minimum_score_gate(self):
        task = TaskProfile(
            task_id="feedback-threshold",
            required_capabilities={"conversation": 0.8},
        )

        report = evaluate_model_decisions(
            [sample_models()[0]],
            [task],
            minimum_scores={"feedback-threshold": 105.0},
            feedback=[
                DecisionOutcomeRecord(
                    record_id="feedback-1",
                    report_path="decision-report.json",
                    report_sha256="0" * 64,
                    generated_at="2026-04-10T12:00:00+00:00",
                    selected_model_id="local-gemma3-heretic",
                    selected_provider="local",
                    verdict="failure",
                )
            ],
        )

        local_rank = report.situations["feedback-threshold"].ranked[0]

        self.assertFalse(report.situations["feedback-threshold"].eligible)
        self.assertFalse(local_rank.eligible)
        self.assertTrue(any("outcome feedback adjustment" in reason for reason in local_rank.reasons))
        self.assertTrue(any("below minimum score 105.00" in blocker for blocker in local_rank.blockers))

    def test_report_surfaces_per_model_and_provider_coverage(self):
        report = evaluate_model_decisions(sample_models(), sample_tasks())

        local_coverage = report.aggregate.model_coverage["local-gemma3-heretic"]
        cli_coverage = report.aggregate.model_coverage["cli-codex-high"]
        api_coverage = report.aggregate.provider_coverage["api"]

        self.assertEqual(report.aggregate.total_weight, 3.0)
        self.assertEqual(report.aggregate.selected_weight, 3.0)
        self.assertEqual(local_coverage.selected_situations, ("private-chat",))
        self.assertEqual(local_coverage.selected_weight, 1.0)
        self.assertIn("hard-coding", local_coverage.blocked_situations)
        self.assertTrue(any("tool support" in blocker for blocker in local_coverage.blocked_situations["hard-coding"]))
        self.assertEqual(cli_coverage.selected_situations, ("hard-coding",))
        self.assertEqual(cli_coverage.weighted_average_score, cli_coverage.average_eligible_score)
        self.assertEqual(api_coverage.selected_situations, ("long-memory",))
        self.assertEqual(api_coverage.selected_weight, 1.0)
        self.assertIn("cli-codex-high", report.aggregate.provider_coverage["cli"].model_ids)

    def test_weighted_decisions_surface_importance_in_aggregate_coverage(self):
        report = evaluate_model_decisions(
            sample_models(),
            sample_tasks(),
            situation_weights={"private-chat": 5.0, "hard-coding": 2.0, "long-memory": 1.0},
        )

        self.assertEqual(report.aggregate.total_weight, 8.0)
        self.assertEqual(report.aggregate.selected_weight, 8.0)
        self.assertEqual(report.situations["private-chat"].weight, 5.0)
        self.assertEqual(report.aggregate.model_coverage["local-gemma3-heretic"].selected_weight, 5.0)
        self.assertEqual(report.aggregate.model_coverage["cli-codex-high"].selected_weight, 2.0)
        self.assertEqual(report.aggregate.provider_coverage["local"].selected_weight, 5.0)
        self.assertGreater(report.summaries[0].selected_weight, report.summaries[-1].selected_weight)

    def test_minimum_score_threshold_blocks_underqualified_winner(self):
        task = TaskProfile(
            task_id="threshold-chat",
            required_capabilities={"conversation": 0.5},
        )

        report = evaluate_model_decisions(
            [sample_models()[0]],
            [task],
            minimum_scores={"threshold-chat": 120.0},
        )
        decision = report.situations["threshold-chat"]

        self.assertFalse(decision.eligible)
        self.assertIsNone(decision.selected)
        self.assertEqual(decision.minimum_score, 120.0)
        self.assertEqual(report.aggregate.blocked_weight, 1.0)
        self.assertTrue(
            any(
                "below minimum score 120.00" in blocker
                for blocker in decision.blockers["local-gemma3-heretic"]
            )
        )

    def test_uncovered_situation_returns_blockers_without_raising(self):
        task = TaskProfile(
            task_id="impossible-local-coder",
            required_capabilities={"coding": 0.99},
            privacy_requirement="local_only",
        )

        report = evaluate_model_decisions(sample_models(), [task])
        decision = report.situations["impossible-local-coder"]

        self.assertFalse(decision.eligible)
        self.assertIsNone(report.selected_for("impossible-local-coder"))
        self.assertIn("local-gemma3-heretic", decision.blockers)
        self.assertTrue(any("coding capability" in blocker for blocker in decision.blockers["local-gemma3-heretic"]))
        self.assertTrue(any("uncovered situations" in reason for reason in report.aggregate.rationale))

    def test_report_serializes_stable_json_ready_shape(self):
        report = evaluate_model_decisions(sample_models(), sample_tasks())

        payload = report.to_dict()

        self.assertEqual(payload["situations"]["private-chat"]["selectedModelId"], "local-gemma3-heretic")
        self.assertEqual(payload["aggregate"]["modelCount"], 3)
        self.assertEqual(payload["aggregate"]["situationCount"], 3)
        self.assertIn("providerCoverage", payload["aggregate"])
        self.assertIn("rationale", payload["situations"]["hard-coding"])

    def test_load_decision_suite_parses_reusable_situations(self):
        payload = {
            "schemaVersion": 1,
            "suiteId": "primary-routing",
            "description": "Reusable model decision suite.",
            "situations": [
                {
                    "taskId": "private-chat",
                    "privacyRequirement": "local_only",
                    "requiredCapabilities": {"conversation": 0.8},
                },
                {
                    "taskId": "hard-coding",
                    "requireTools": True,
                    "requiredCapabilities": {"coding": 0.9},
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "suite.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            suite = load_decision_suite(path)

        self.assertEqual(suite.suite_id, "primary-routing")
        self.assertEqual(suite.description, "Reusable model decision suite.")
        self.assertEqual([task.task_id for task in suite.situations], ["private-chat", "hard-coding"])
        self.assertEqual(suite.weight_for("private-chat"), 1.0)
        self.assertIsNone(suite.minimum_score_for("hard-coding"))

    def test_decision_suite_parses_weight_and_minimum_score_policy(self):
        payload = {
            "schemaVersion": 1,
            "suiteId": "calibrated",
            "situations": [
                {
                    "taskId": "private-chat",
                    "weight": 4.5,
                    "minimumScore": 110.0,
                    "requiredCapabilities": {"conversation": 0.8},
                }
            ],
        }

        suite = parse_decision_suite(payload)
        report = evaluate_model_decisions(sample_models(), suite)

        self.assertEqual(suite.weight_for("private-chat"), 4.5)
        self.assertEqual(suite.minimum_score_for("private-chat"), 110.0)
        self.assertEqual(report.situations["private-chat"].weight, 4.5)
        self.assertEqual(report.situations["private-chat"].minimum_score, 110.0)
        self.assertEqual(report.aggregate.total_weight, 4.5)

    def test_decision_suite_rejects_duplicate_situations(self):
        payload = {
            "schemaVersion": 1,
            "suiteId": "broken",
            "situations": [
                {"taskId": "duplicate", "requiredCapabilities": {"conversation": 0.5}},
                {"taskId": "duplicate", "requiredCapabilities": {"coding": 0.5}},
            ],
        }

        with self.assertRaises(ModelDecisionError) as error:
            parse_decision_suite(payload)

        self.assertIn("duplicate task ids", str(error.exception))

    def test_decision_policy_rejects_unknown_task_ids(self):
        task = TaskProfile(task_id="known", required_capabilities={"conversation": 0.5})

        with self.assertRaises(ModelDecisionError) as error:
            evaluate_model_decisions(sample_models(), [task], situation_weights={"unknown": 2.0})

        self.assertIn("unknown task ids", str(error.exception))

    def test_rejects_duplicate_task_ids(self):
        task = TaskProfile(task_id="duplicate", required_capabilities={"conversation": 0.5})

        with self.assertRaises(ModelDecisionError) as error:
            evaluate_model_decisions(sample_models(), [task, task])

        self.assertIn("duplicate task ids", str(error.exception))

    def test_rejects_explicit_empty_task_list(self):
        with self.assertRaises(ModelDecisionError) as error:
            evaluate_model_decisions(sample_models(), [])

        self.assertIn("At least one task profile", str(error.exception))


if __name__ == "__main__":
    unittest.main()
