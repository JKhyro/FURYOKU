import json
import tempfile
import unittest
from pathlib import Path

from furyoku import (
    ApprovalResumeError,
    approval_resume_record_from_workflow_envelope,
    load_approval_resume_ledger,
    load_approval_resume_record,
    parse_approval_resume_ledger,
    parse_approval_resume_record,
    parse_operator_reviewed_workflow_envelope,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples" / "hermes_approval_resume_contract.example.json"
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
