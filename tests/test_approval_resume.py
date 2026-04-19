import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from furyoku import (
    ApprovalResumeConsumptionEvent,
    ApprovalResumeError,
    LocalApprovalResumeLedgerAdapter,
    approval_resume_record_from_workflow_envelope,
    build_local_approval_resume_store_report,
    load_approval_resume_ledger,
    load_approval_resume_record,
    load_local_approval_resume_ledger_adapter,
    parse_approval_resume_ledger,
    parse_approval_resume_record,
    parse_operator_reviewed_workflow_envelope,
)
from furyoku.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples" / "hermes_approval_resume_contract.example.json"
OPERATOR_RESUME_WORKFLOW_PATH = ROOT / "examples" / "operator_resume_workflow.example.json"
SEVEN_SMOKE_ENVELOPE_PATH = ROOT / "examples" / "hermes_bridge_seven_symbiote.example.json"
SEVEN_SMOKE_APPROVAL_PATH = ROOT / "examples" / "hermes_approval_resume_seven_smoke.approved.json"
HANDOFF_EXECUTION_KEY = "symbiote-01:primary:hermes.bridge.one-symbiote"
WORKFLOW_ID = "operator.reviewed.hermes-handoff"
EXECUTION_ID = "reviewed-handoff-001"
WORKFLOW_EXECUTION_KEY = f"{WORKFLOW_ID}:{EXECUTION_ID}:{HANDOFF_EXECUTION_KEY}"


def record_payload(**overrides) -> dict:
    payload = {
        "schemaVersion": 1,
        "workflowId": WORKFLOW_ID,
        "executionId": EXECUTION_ID,
        "handoffExecutionKey": HANDOFF_EXECUTION_KEY,
        "attemptIndex": 1,
        "recordState": "approval_pending",
        "owner": "furyoku-operator",
        "createdAtUtc": "2026-04-19T00:00:00Z",
        "evidence": {
            "workflowEnvelope": "docs/operator-reviewed-workflow-envelope.md",
            "issue": "#248",
        },
    }
    payload.update(overrides)
    return payload


def workflow_payload() -> dict:
    return {
        "schemaVersion": 1,
        "workflowId": WORKFLOW_ID,
        "executionId": EXECUTION_ID,
        "review": {
            "approvalState": "approval_required",
            "requestedBy": "furyoku-operator",
        },
        "handoff": {
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
            "prompt": "Confirm the reviewed Hermes/FURYOKU handoff.",
        },
        "evidence": {
            "issue": "#248",
        },
    }


class ApprovalResumeContractTests(unittest.TestCase):
    def test_parses_pending_approval_record(self):
        record = parse_approval_resume_record(record_payload())
        payload = record.to_dict()

        self.assertEqual(record.workflow_execution_key, WORKFLOW_EXECUTION_KEY)
        self.assertEqual(record.record_key, f"{WORKFLOW_EXECUTION_KEY}:attempt:1")
        self.assertFalse(record.safe_to_handoff)
        self.assertFalse(record.is_resume)
        self.assertTrue(payload["guardrails"]["executionKeyed"])
        self.assertFalse(payload["guardrails"]["hiddenSharedStateAllowed"])

    def test_builds_pending_record_from_workflow_envelope(self):
        envelope = parse_operator_reviewed_workflow_envelope(workflow_payload())

        record = approval_resume_record_from_workflow_envelope(envelope, owner="furyoku-operator")

        self.assertEqual(record.state, "approval_pending")
        self.assertEqual(record.workflow_execution_key, WORKFLOW_EXECUTION_KEY)
        self.assertEqual(record.evidence["issue"], "#248")

    def test_approved_record_requires_operator_identity(self):
        with self.assertRaises(ApprovalResumeError) as error:
            parse_approval_resume_record(record_payload(recordState="approved"))

        self.assertIn("approved", str(error.exception))
        self.assertIn("approvedBy", str(error.exception))

    def test_approved_record_is_safe_to_handoff(self):
        record = parse_approval_resume_record(
            record_payload(
                recordState="approved",
                approvedBy="operator",
                approvedAtUtc="2026-04-19T01:00:00Z",
            )
        )

        self.assertTrue(record.safe_to_handoff)
        self.assertFalse(record.is_resume)

    def test_resume_record_requires_explicit_intent(self):
        with self.assertRaises(ApprovalResumeError) as error:
            parse_approval_resume_record(
                record_payload(recordState="resume_requested", attemptIndex=2)
            )

        self.assertIn("requires resume intent", str(error.exception))

    def test_replay_attempt_requires_explicit_resume_intent(self):
        with self.assertRaises(ApprovalResumeError) as error:
            parse_approval_resume_record(record_payload(attemptIndex=2))

        self.assertIn("explicit resume intent", str(error.exception))

    def test_resume_record_binds_to_same_workflow_execution_key(self):
        record = parse_approval_resume_record(
            record_payload(
                recordState="resume_requested",
                attemptIndex=2,
                resume={
                    "resumeOf": WORKFLOW_EXECUTION_KEY,
                    "previousAttemptIndex": 1,
                    "requestedBy": "operator",
                    "reason": "provider timeout was recoverable",
                },
            )
        )

        self.assertTrue(record.is_resume)
        self.assertFalse(record.safe_to_handoff)
        self.assertEqual(record.resume.resume_of, WORKFLOW_EXECUTION_KEY)

    def test_resume_record_rejects_mismatched_resume_key(self):
        with self.assertRaises(ApprovalResumeError) as error:
            parse_approval_resume_record(
                record_payload(
                    recordState="resume_requested",
                    attemptIndex=2,
                    resume={
                        "resumeOf": "wrong:key",
                        "previousAttemptIndex": 1,
                        "requestedBy": "operator",
                        "reason": "retry",
                    },
                )
            )

        self.assertIn("resume.resumeOf", str(error.exception))

    def test_ledger_rejects_duplicate_record_keys(self):
        payload = {
            "schemaVersion": 1,
            "records": [record_payload(), record_payload()],
        }

        with self.assertRaises(ApprovalResumeError) as error:
            parse_approval_resume_ledger(payload)

        self.assertIn("duplicate approval/resume record", str(error.exception))

    def test_ledger_rejects_ambiguous_record_ownership(self):
        payload = {
            "schemaVersion": 1,
            "records": [
                record_payload(owner="operator-a"),
                record_payload(owner="operator-b"),
            ],
        }

        with self.assertRaises(ApprovalResumeError) as error:
            parse_approval_resume_ledger(payload)

        self.assertIn("ambiguous ownership", str(error.exception))

    def test_local_adapter_appends_and_reads_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "approval-store.json"
            adapter = load_local_approval_resume_ledger_adapter(path)
            record = parse_approval_resume_record(
                record_payload(
                    recordState="approved",
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T01:00:00Z",
                )
            )

            adapter.append_record(record)
            reloaded = LocalApprovalResumeLedgerAdapter(path)

            self.assertEqual(len(reloaded.records), 1)
            self.assertEqual(reloaded.records[0].record_key, record.record_key)
            latest = reloaded.latest_gate_record(HANDOFF_EXECUTION_KEY)
            self.assertIsNotNone(latest)
            self.assertEqual(latest.record_key, record.record_key)
            self.assertEqual(reloaded.to_dict()["records"][0]["recordKey"], record.record_key)

    def test_local_adapter_selects_latest_gate_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = LocalApprovalResumeLedgerAdapter(Path(temp_dir) / "approval-store.json")
            first = parse_approval_resume_record(
                record_payload(
                    recordState="approved",
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T01:00:00Z",
                    createdAtUtc="2026-04-19T01:00:00Z",
                )
            )
            resumed = parse_approval_resume_record(
                record_payload(
                    recordState="resume_approved",
                    attemptIndex=2,
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T02:00:00Z",
                    createdAtUtc="2026-04-19T02:00:00Z",
                    resume={
                        "resumeOf": WORKFLOW_EXECUTION_KEY,
                        "previousAttemptIndex": 1,
                        "requestedBy": "operator",
                        "reason": "recoverable handoff retry",
                    },
                )
            )

            adapter.append_record(first)
            adapter.append_record(resumed)
            selected = adapter.select_gate_record_for_handoff(HANDOFF_EXECUTION_KEY)

        self.assertEqual(selected.record_key, resumed.record_key)
        self.assertEqual(selected.state, "resume_approved")
        self.assertEqual(selected.attempt_index, 2)

    def test_local_adapter_blocks_ambiguous_workflow_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = LocalApprovalResumeLedgerAdapter(Path(temp_dir) / "approval-store.json")
            first = parse_approval_resume_record(
                record_payload(
                    recordState="approved",
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T01:00:00Z",
                )
            )
            second = parse_approval_resume_record(
                record_payload(
                    workflowId="operator.reviewed.other-workflow",
                    executionId="other-execution-001",
                    recordState="approved",
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T01:05:00Z",
                )
            )

            adapter.append_record(first)
            adapter.append_record(second)
            with self.assertRaises(ApprovalResumeError) as error:
                adapter.latest_gate_record(HANDOFF_EXECUTION_KEY)
            selected = adapter.latest_gate_record(
                HANDOFF_EXECUTION_KEY,
                workflow_execution_key=second.workflow_execution_key,
            )

        self.assertIn("multiple workflow executions", str(error.exception))
        self.assertEqual(selected.record_key, second.record_key)

    def test_local_adapter_blocks_consumed_record_replay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = LocalApprovalResumeLedgerAdapter(Path(temp_dir) / "approval-store.json")
            record = parse_approval_resume_record(
                record_payload(
                    recordState="approved",
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T01:00:00Z",
                )
            )

            adapter.append_record(record)
            selected = adapter.select_gate_record_for_handoff(HANDOFF_EXECUTION_KEY)
            adapter.append_consumption_event(
                ApprovalResumeConsumptionEvent.from_record(
                    selected,
                    execution_key="bridge-run-001",
                    result_status="succeeded",
                    started_at_utc="2026-04-19T01:01:00Z",
                    finished_at_utc="2026-04-19T01:02:00Z",
                )
            )

            self.assertTrue(adapter.is_record_consumed(record.record_key))
            with self.assertRaises(ApprovalResumeError) as error:
                adapter.select_gate_record_for_handoff(HANDOFF_EXECUTION_KEY)

        self.assertIn("already consumed", str(error.exception))

    def test_local_store_report_summarizes_ready_and_consumed_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = LocalApprovalResumeLedgerAdapter(Path(temp_dir) / "approval-store.json")
            record = parse_approval_resume_record(
                record_payload(
                    recordState="approved",
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T01:00:00Z",
                )
            )

            adapter.append_record(record)
            ready_report = build_local_approval_resume_store_report(
                adapter,
                handoff_execution_key=HANDOFF_EXECUTION_KEY,
            )
            adapter.append_consumption_event(
                ApprovalResumeConsumptionEvent.from_record(
                    record,
                    execution_key="bridge-run-001",
                    result_status="succeeded",
                    started_at_utc="2026-04-19T01:01:00Z",
                    finished_at_utc="2026-04-19T01:02:00Z",
                )
            )
            consumed_report = build_local_approval_resume_store_report(
                adapter,
                handoff_execution_key=HANDOFF_EXECUTION_KEY,
            )

        self.assertTrue(ready_report["gate"]["ready"])
        self.assertEqual(ready_report["gate"]["status"], "ready")
        self.assertEqual(ready_report["summary"]["readyRecords"], 1)
        self.assertEqual(ready_report["records"][0]["gateStatus"], "ready")
        self.assertFalse(consumed_report["gate"]["ready"])
        self.assertEqual(consumed_report["gate"]["status"], "blocked")
        self.assertEqual(consumed_report["gate"]["error"]["code"], "approval_resume_record_consumed")
        self.assertEqual(consumed_report["summary"]["readyRecords"], 0)
        self.assertEqual(consumed_report["summary"]["consumedRecords"], 1)
        self.assertEqual(consumed_report["records"][0]["gateStatus"], "consumed")
        self.assertEqual(consumed_report["records"][0]["consumptionEvents"][0]["executionKey"], "bridge-run-001")

    def test_cli_reports_local_store_without_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "approval-store.json"
            adapter = LocalApprovalResumeLedgerAdapter(path)
            adapter.append_record(
                parse_approval_resume_record(
                    record_payload(
                        recordState="approved",
                        approvedBy="operator",
                        approvedAtUtc="2026-04-19T01:00:00Z",
                    )
                )
            )
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = cli_main(
                    [
                        "approval-resume-store-report",
                        "--store",
                        str(path),
                        "--handoff-execution-key",
                        HANDOFF_EXECUTION_KEY,
                    ]
                )
            report = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["reportType"], "local-approval-resume-store")
        self.assertEqual(report["gate"]["status"], "ready")
        self.assertEqual(report["summary"]["filteredRecords"], 1)
        self.assertEqual(report["records"][0]["handoffExecutionKey"], HANDOFF_EXECUTION_KEY)

    def test_local_adapter_rejects_consumption_event_for_wrong_handoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = LocalApprovalResumeLedgerAdapter(Path(temp_dir) / "approval-store.json")
            record = parse_approval_resume_record(
                record_payload(
                    recordState="approved",
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T01:00:00Z",
                )
            )
            event = ApprovalResumeConsumptionEvent(
                schema_version=1,
                record_key=record.record_key,
                handoff_execution_key="symbiote-02:secondary:hermes.bridge.other",
                execution_key="bridge-run-001",
                result_status="succeeded",
            )

            adapter.append_record(record)
            with self.assertRaises(ApprovalResumeError) as error:
                adapter.append_consumption_event(event)

        self.assertIn("handoffExecutionKey does not match", str(error.exception))

    def test_local_adapter_rejects_duplicate_record_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = LocalApprovalResumeLedgerAdapter(Path(temp_dir) / "approval-store.json")
            record = parse_approval_resume_record(
                record_payload(
                    recordState="approved",
                    approvedBy="operator",
                    approvedAtUtc="2026-04-19T01:00:00Z",
                )
            )

            adapter.append_record(record)
            with self.assertRaises(ApprovalResumeError) as error:
                adapter.append_record(record)

        self.assertIn("duplicate approval/resume record", str(error.exception))

    def test_record_rejects_hidden_shared_state_fields(self):
        with self.assertRaises(ApprovalResumeError) as error:
            parse_approval_resume_record(record_payload(sharedState={"hidden": True}))

        self.assertIn("hidden shared state", str(error.exception))
        self.assertIn("sharedState", str(error.exception))

    def test_checked_in_example_loads_as_ledger(self):
        ledger = load_approval_resume_ledger(EXAMPLE_PATH)

        self.assertEqual(len(ledger.records), 2)
        self.assertIn(WORKFLOW_EXECUTION_KEY, ledger.workflow_execution_keys)
        self.assertTrue(ledger.records[1].is_resume)

    def test_checked_in_operator_resume_workflow_fixture_is_safe_retry(self):
        ledger = load_approval_resume_ledger(OPERATOR_RESUME_WORKFLOW_PATH)
        resume_record = ledger.records[1]

        self.assertEqual(len(ledger.records), 2)
        self.assertEqual(resume_record.state, "resume_approved")
        self.assertEqual(resume_record.attempt_index, 2)
        self.assertTrue(resume_record.safe_to_handoff)
        self.assertTrue(resume_record.is_resume)
        self.assertEqual(resume_record.resume.resume_of, WORKFLOW_EXECUTION_KEY)
        self.assertEqual(resume_record.resume.previous_attempt_index, 1)
        self.assertEqual(resume_record.evidence["issue"], "#266")
        self.assertIn("consumptionEventKey", resume_record.evidence)

    def test_checked_in_seven_smoke_fixture_matches_smoke_execution_keys(self):
        ledger = load_approval_resume_ledger(SEVEN_SMOKE_APPROVAL_PATH)
        smoke_payload = json.loads(SEVEN_SMOKE_ENVELOPE_PATH.read_text(encoding="utf-8"))
        expected_keys = [
            f"{symbiote['symbioteId']}:{symbiote['role']}:{symbiote['task']['taskId']}"
            for symbiote in smoke_payload["symbiotes"]
        ]

        self.assertEqual(len(ledger.records), 7)
        self.assertEqual([record.handoff_execution_key for record in ledger.records], expected_keys)
        self.assertTrue(all(record.safe_to_handoff for record in ledger.records))
        self.assertEqual({record.evidence["issue"] for record in ledger.records}, {"#254"})

    def test_loads_single_record_from_json_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "approval-record.json"
            path.write_text(json.dumps(record_payload()), encoding="utf-8")

            record = load_approval_resume_record(path)

        self.assertEqual(record.source, str(path))


if __name__ == "__main__":
    unittest.main()
