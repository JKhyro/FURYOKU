import json
import tempfile
import unittest
from pathlib import Path

from furyoku import (
    DecisionOutcomeRecord,
    FeedbackAdjustmentPolicy,
    OutcomeFeedbackError,
    append_decision_outcome,
    build_feedback_policy_metadata,
    build_model_feedback_summaries,
    capture_comparative_execution_outcomes,
    capture_execution_outcome,
    create_comparative_execution_outcome_records,
    create_decision_outcome_record,
    create_execution_outcome_record,
    infer_execution_outcome_verdict,
    load_decision_outcomes,
    load_feedback_adjustment_policy,
    parse_feedback_adjustment_policy,
    resolve_feedback_adjustment_policy,
    summarize_outcome_feedback,
)


def write_execution_report(path: Path) -> None:
    payload = {
        "reportMetadata": {
            "schemaVersion": 1,
            "generatedAt": "2026-04-10T12:00:00+00:00",
        },
        "ok": True,
        "situationId": "decision.private-chat",
        "selectedModel": {
            "modelId": "local-gemma3-heretic-q4",
            "provider": "local",
        },
        "execution": {
            "status": "ok",
            "elapsedMs": 1200,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_comparison_report(path: Path) -> None:
    payload = {
        "reportMetadata": {
            "schemaVersion": 1,
            "generatedAt": "2026-04-10T12:30:00+00:00",
        },
        "ok": True,
        "taskId": "fallback-chat",
        "comparison": {
            "executedCount": 2,
            "successfulCount": 1,
            "failedCount": 1,
        },
        "executions": [
            {
                "attemptNumber": 1,
                "selectedModel": {
                    "modelId": "local-failing",
                    "provider": "local",
                },
                "execution": {
                    "status": "error",
                    "stderr": "local failed",
                },
            },
            {
                "attemptNumber": 2,
                "selectedModel": {
                    "modelId": "cli-fallback",
                    "provider": "cli",
                },
                "execution": {
                    "status": "ok",
                    "responseText": "fallback:hello",
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class OutcomeFeedbackTests(unittest.TestCase):
    def test_create_feedback_record_links_to_persisted_execution_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "run-report.json"
            write_execution_report(report_path)

            record = create_decision_outcome_record(
                report_path,
                verdict="success",
                score=0.92,
                reason="good local response",
                tags=("local", "private-chat"),
            )

        payload = record.to_dict()
        self.assertEqual(payload["reportGeneratedAt"], "2026-04-10T12:00:00+00:00")
        self.assertEqual(payload["situationId"], "decision.private-chat")
        self.assertEqual(payload["selectedModelId"], "local-gemma3-heretic-q4")
        self.assertEqual(payload["selectedProvider"], "local")
        self.assertEqual(payload["executionStatus"], "ok")
        self.assertEqual(payload["verdict"], "success")
        self.assertEqual(payload["score"], 0.92)
        self.assertEqual(payload["tags"], ["local", "private-chat"])
        self.assertEqual(len(payload["reportSha256"]), 64)

    def test_append_and_load_feedback_log_preserves_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "run-report.json"
            log_path = Path(temp_dir) / "feedback" / "outcomes.jsonl"
            write_execution_report(report_path)
            record = create_decision_outcome_record(report_path, verdict="quality_concern", reason="too terse")

            append_decision_outcome(log_path, record)
            loaded = load_decision_outcomes(log_path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].record_id, record.record_id)
        self.assertEqual(loaded[0].verdict, "quality_concern")
        self.assertEqual(loaded[0].reason, "too terse")

    def test_create_execution_outcome_record_infers_success_from_persisted_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "run-report.json"
            write_execution_report(report_path)

            record = create_execution_outcome_record(
                report_path,
                score=0.97,
                reason="accepted generated answer",
                tags=("auto-capture",),
            )

        self.assertEqual(record.verdict, "success")
        self.assertEqual(record.score, 0.97)
        self.assertEqual(record.reason, "accepted generated answer")
        self.assertEqual(record.tags, ("auto-capture",))
        self.assertEqual(record.selected_model_id, "local-gemma3-heretic-q4")
        self.assertEqual(record.execution_status, "ok")

    def test_capture_execution_outcome_appends_inferred_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "failed-run.json"
            feedback_path = Path(temp_dir) / "feedback" / "outcomes.jsonl"
            report_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "selection": {"modelId": "local-broken", "provider": "local"},
                        "execution": {"status": "error", "stderr": "bad runtime"},
                    }
                ),
                encoding="utf-8",
            )

            record = capture_execution_outcome(feedback_path, report_path, reason="provider failed")
            loaded = load_decision_outcomes(feedback_path)

        self.assertEqual(record.verdict, "failure")
        self.assertEqual(record.execution_status, "error")
        self.assertEqual(loaded[0].record_id, record.record_id)
        self.assertEqual(loaded[0].selected_model_id, "local-broken")

    def test_create_comparative_execution_outcome_records_preserves_per_candidate_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "comparison.json"
            write_comparison_report(report_path)

            records = create_comparative_execution_outcome_records(
                report_path,
                success_score=1.0,
                failure_score=0.0,
                reason="comparison capture",
                tags=("comparison",),
                metadata={"operator": "test"},
            )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].selected_model_id, "local-failing")
        self.assertEqual(records[0].verdict, "failure")
        self.assertEqual(records[0].score, 0.0)
        self.assertEqual(records[0].execution_status, "error")
        self.assertEqual(records[0].metadata["comparisonAttemptNumber"], 1)
        self.assertEqual(records[0].metadata["operator"], "test")
        self.assertEqual(records[1].selected_model_id, "cli-fallback")
        self.assertEqual(records[1].verdict, "success")
        self.assertEqual(records[1].score, 1.0)
        self.assertEqual(records[1].metadata["comparisonExecutedCount"], 2)

    def test_capture_comparative_execution_outcomes_appends_all_candidate_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "comparison.json"
            feedback_path = Path(temp_dir) / "feedback" / "comparison-outcomes.jsonl"
            write_comparison_report(report_path)

            records = capture_comparative_execution_outcomes(
                feedback_path,
                report_path,
                reason="operator comparison",
            )
            loaded = load_decision_outcomes(feedback_path)

        self.assertEqual(len(records), 2)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].selected_model_id, "local-failing")
        self.assertEqual(loaded[0].verdict, "failure")
        self.assertEqual(loaded[1].selected_model_id, "cli-fallback")
        self.assertEqual(loaded[1].verdict, "success")

    def test_infer_execution_outcome_rejects_reports_without_execution_status(self):
        with self.assertRaises(OutcomeFeedbackError) as error:
            infer_execution_outcome_verdict({"schemaVersion": 1})

        self.assertIn("execution.status", str(error.exception))

    def test_rejects_invalid_feedback_verdict_and_score(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "run-report.json"
            write_execution_report(report_path)

            with self.assertRaises(OutcomeFeedbackError) as verdict_error:
                create_decision_outcome_record(report_path, verdict="maybe")
            with self.assertRaises(OutcomeFeedbackError) as score_error:
                create_decision_outcome_record(report_path, verdict="success", score=1.5)

        self.assertIn("verdict", str(verdict_error.exception))
        self.assertIn("score", str(score_error.exception))

    def test_build_feedback_summaries_bounds_model_adjustments(self):
        records = [
            DecisionOutcomeRecord(
                record_id="1",
                report_path="report.json",
                report_sha256="0" * 64,
                generated_at="2026-04-10T12:00:00+00:00",
                selected_model_id="local-model",
                selected_provider="local",
                verdict="success",
                score=1.0,
            ),
            DecisionOutcomeRecord(
                record_id="2",
                report_path="report.json",
                report_sha256="1" * 64,
                generated_at="2026-04-10T12:01:00+00:00",
                selected_model_id="remote-model",
                selected_provider="api",
                override_model_id="local-model",
                verdict="manual_override",
            ),
        ]

        summaries = build_model_feedback_summaries(records, max_adjustment=12.0)

        self.assertGreater(summaries["local-model"].adjustment, 0.0)
        self.assertLess(summaries["remote-model"].adjustment, 0.0)
        self.assertEqual(summaries["local-model"].manual_override_count, 1)
        self.assertTrue(any("bounded feedback adjustment" in reason for reason in summaries["local-model"].rationale))

    def test_summarize_outcome_feedback_reports_model_provider_and_situation_rollups(self):
        records = [
            DecisionOutcomeRecord(
                record_id="1",
                report_path="report-1.json",
                report_sha256="0" * 64,
                generated_at="2026-04-10T12:00:00+00:00",
                situation_id="private-chat",
                selected_model_id="local-model",
                selected_provider="local",
                verdict="success",
                score=0.9,
            ),
            DecisionOutcomeRecord(
                record_id="2",
                report_path="report-2.json",
                report_sha256="1" * 64,
                generated_at="2026-04-10T12:01:00+00:00",
                situation_id="private-chat",
                selected_model_id="local-model",
                selected_provider="local",
                verdict="failure",
                score=0.2,
            ),
            DecisionOutcomeRecord(
                record_id="3",
                report_path="report-3.json",
                report_sha256="2" * 64,
                generated_at="2026-04-10T12:02:00+00:00",
                situation_id="coding",
                selected_model_id="api-model",
                selected_provider="api",
                verdict="quality_concern",
                score=0.4,
            ),
            DecisionOutcomeRecord(
                record_id="4",
                report_path="report-4.json",
                report_sha256="3" * 64,
                generated_at="2026-04-10T12:03:00+00:00",
                situation_id="coding",
                selected_model_id="api-model",
                selected_provider="api",
                override_model_id="local-model",
                verdict="manual_override",
                score=0.8,
            ),
        ]

        report = summarize_outcome_feedback(records, generated_at="2026-04-11T00:00:00+00:00")
        payload = report.to_dict()

        self.assertEqual(payload["recordCount"], 4)
        self.assertEqual(payload["generatedAt"], "2026-04-11T00:00:00+00:00")
        self.assertEqual(payload["total"]["successCount"], 1)
        self.assertEqual(payload["total"]["failureCount"], 1)
        self.assertEqual(payload["total"]["concernCount"], 1)
        self.assertEqual(payload["total"]["manualOverrideCount"], 1)
        self.assertEqual(payload["total"]["averageScore"], 0.575)
        self.assertEqual(payload["models"][0]["key"], "local-model")
        self.assertGreater(payload["models"][0]["rankScore"], payload["models"][1]["rankScore"])
        self.assertEqual(payload["models"][0]["recordCount"], 2)
        self.assertEqual(payload["models"][0]["weightedRecordCount"], 3.0)
        self.assertEqual(payload["providers"][0]["key"], "local")
        self.assertEqual([summary["key"] for summary in payload["situations"]], ["coding", "private-chat"])
        self.assertEqual(payload["feedbackPolicy"]["source"], "default")

    def test_summarize_outcome_feedback_accepts_empty_records(self):
        payload = summarize_outcome_feedback((), generated_at="2026-04-11T00:00:00+00:00").to_dict()

        self.assertEqual(payload["recordCount"], 0)
        self.assertEqual(payload["total"]["recordCount"], 0)
        self.assertEqual(payload["total"]["successRate"], 0.0)
        self.assertEqual(payload["models"], [])
        self.assertEqual(payload["providers"], [])
        self.assertEqual(payload["situations"], [])

    def test_custom_feedback_policy_changes_adjustment_size(self):
        records = [
            DecisionOutcomeRecord(
                record_id="1",
                report_path="report.json",
                report_sha256="0" * 64,
                generated_at="2026-04-10T12:00:00+00:00",
                selected_model_id="local-model",
                selected_provider="local",
                verdict="success",
                score=1.0,
            )
        ]
        policy = FeedbackAdjustmentPolicy(
            max_adjustment=5.0,
            success_base=1.0,
            success_score_multiplier=2.0,
        )

        summaries = build_model_feedback_summaries(records, policy=policy)

        self.assertEqual(summaries["local-model"].adjustment, 3.0)
        self.assertEqual(summaries["local-model"].weighted_record_count, 1.0)

    def test_feedback_policy_metadata_surfaces_default_contract(self):
        metadata = build_feedback_policy_metadata()
        payload = metadata.to_dict()

        self.assertEqual(metadata.source, "default")
        self.assertEqual(metadata.customized_fields, ())
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["source"], "default")
        self.assertEqual(payload["customizedFields"], [])
        self.assertEqual(payload["policy"]["maxAdjustment"], 12.0)
        self.assertEqual(resolve_feedback_adjustment_policy(), metadata.policy)

    def test_feedback_policy_metadata_tracks_custom_fields(self):
        metadata = build_feedback_policy_metadata(
            FeedbackAdjustmentPolicy(
                max_adjustment=4.0,
                success_base=1.0,
                recency_half_life_days=7.0,
            )
        )
        payload = metadata.to_dict()

        self.assertEqual(metadata.source, "custom")
        self.assertEqual(payload["source"], "custom")
        self.assertEqual(
            payload["customizedFields"],
            ["maxAdjustment", "recencyHalfLifeDays", "successBase"],
        )
        self.assertEqual(payload["policy"]["maxAdjustment"], 4.0)
        self.assertEqual(payload["policy"]["successBase"], 1.0)
        self.assertEqual(payload["policy"]["recencyHalfLifeDays"], 7.0)

    def test_feedback_policy_supports_recency_half_life(self):
        records = [
            DecisionOutcomeRecord(
                record_id="new",
                report_path="report.json",
                report_sha256="0" * 64,
                generated_at="2026-04-10T00:00:00+00:00",
                selected_model_id="local-model",
                selected_provider="local",
                verdict="success",
                score=1.0,
            ),
            DecisionOutcomeRecord(
                record_id="old",
                report_path="report.json",
                report_sha256="1" * 64,
                generated_at="2026-04-09T00:00:00+00:00",
                selected_model_id="local-model",
                selected_provider="local",
                verdict="failure",
            ),
        ]

        summaries = build_model_feedback_summaries(
            records,
            policy=FeedbackAdjustmentPolicy(recency_half_life_days=1.0),
            as_of="2026-04-10T00:00:00+00:00",
        )

        self.assertGreater(summaries["local-model"].adjustment, 0.0)
        self.assertEqual(summaries["local-model"].weighted_record_count, 1.5)
        self.assertTrue(any("recency half-life" in reason for reason in summaries["local-model"].rationale))

    def test_load_feedback_adjustment_policy_parses_json_contract(self):
        payload = {
            "schemaVersion": 1,
            "maxAdjustment": 4.0,
            "successBase": 1.5,
            "successScoreMultiplier": 2.5,
            "failurePenalty": -3.0,
            "recencyHalfLifeDays": 7.0,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_feedback_adjustment_policy(path)

        parsed = parse_feedback_adjustment_policy(payload)
        self.assertEqual(loaded, parsed)
        self.assertEqual(loaded.max_adjustment, 4.0)
        self.assertEqual(loaded.recency_half_life_days, 7.0)

    def test_feedback_loaders_accept_utf8_bom_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "run-report.json"
            feedback_path = Path(temp_dir) / "feedback.jsonl"
            policy_path = Path(temp_dir) / "policy.json"
            write_execution_report(report_path)
            record = create_decision_outcome_record(report_path, verdict="success")
            feedback_path.write_text(
                json.dumps(record.to_dict()) + "\n",
                encoding="utf-8-sig",
            )
            policy_path.write_text(
                json.dumps({"schemaVersion": 1, "maxAdjustment": 4.0}),
                encoding="utf-8-sig",
            )

            feedback = load_decision_outcomes(feedback_path)
            policy = load_feedback_adjustment_policy(policy_path)

        self.assertEqual(feedback[0].record_id, record.record_id)
        self.assertEqual(policy.max_adjustment, 4.0)

    def test_feedback_policy_rejects_invalid_values(self):
        with self.assertRaises(OutcomeFeedbackError):
            FeedbackAdjustmentPolicy(max_adjustment=-1.0)
        with self.assertRaises(OutcomeFeedbackError):
            parse_feedback_adjustment_policy({"schemaVersion": 1, "defaultSuccessScore": 1.5})


if __name__ == "__main__":
    unittest.main()
