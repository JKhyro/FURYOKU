import json
import tempfile
import unittest
from pathlib import Path

from furyoku import (
    DecisionOutcomeRecord,
    OutcomeFeedbackError,
    append_decision_outcome,
    build_model_feedback_summaries,
    create_decision_outcome_record,
    load_decision_outcomes,
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


if __name__ == "__main__":
    unittest.main()
