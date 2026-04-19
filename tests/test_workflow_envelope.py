import json
import tempfile
import unittest
from pathlib import Path

from furyoku import (
    WorkflowEnvelopeError,
    load_operator_reviewed_workflow_envelope,
    parse_operator_reviewed_workflow_envelope,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples" / "operator_reviewed_hermes_workflow.example.json"


def handoff_payload() -> dict:
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
        "prompt": "Confirm the reviewed Hermes/FURYOKU handoff.",
        "routing": {
            "checkHealth": True,
            "fallback": True,
            "maxAttempts": 2,
        },
    }


def workflow_payload() -> dict:
    return {
        "schemaVersion": 1,
        "workflowId": "operator.reviewed.hermes-handoff",
        "executionId": "reviewed-handoff-001",
        "createdAtUtc": "2026-04-19T00:00:00Z",
        "review": {
            "approvalState": "approval_required",
            "requestedBy": "furyoku-operator",
        },
        "handoff": handoff_payload(),
        "evidence": {
            "routingEvidenceContract": "docs/routing-evidence-contract.md",
            "issue": "#246",
        },
    }


class OperatorReviewedWorkflowEnvelopeTests(unittest.TestCase):
    def test_parses_approval_required_workflow_without_starting_handoff(self):
        envelope = parse_operator_reviewed_workflow_envelope(workflow_payload())
        payload = envelope.to_dict()

        self.assertEqual(envelope.workflow_id, "operator.reviewed.hermes-handoff")
        self.assertEqual(envelope.execution_id, "reviewed-handoff-001")
        self.assertEqual(envelope.handoff.execution_key, "symbiote-01:primary:hermes.bridge.one-symbiote")
        self.assertFalse(envelope.safe_to_handoff)
        self.assertTrue(payload["review"]["approvalRequired"])
        self.assertTrue(payload["guardrails"]["singleHandoff"])
        self.assertFalse(payload["guardrails"]["hiddenSharedStateAllowed"])

    def test_approved_review_requires_operator_identity(self):
        payload = workflow_payload()
        payload["review"] = {"approvalState": "approved"}

        with self.assertRaises(WorkflowEnvelopeError) as error:
            parse_operator_reviewed_workflow_envelope(payload)

        self.assertIn("approvedBy", str(error.exception))

    def test_approved_review_can_mark_envelope_safe_to_handoff(self):
        payload = workflow_payload()
        payload["review"] = {
            "approvalState": "approved",
            "approvedBy": "operator",
            "approvedAtUtc": "2026-04-19T01:00:00Z",
        }

        envelope = parse_operator_reviewed_workflow_envelope(payload)

        self.assertTrue(envelope.safe_to_handoff)
        self.assertIn("operator.reviewed.hermes-handoff", envelope.workflow_execution_key)
        self.assertIn("symbiote-01:primary:hermes.bridge.one-symbiote", envelope.workflow_execution_key)

    def test_rejects_missing_execution_identity(self):
        payload = workflow_payload()
        del payload["executionId"]

        with self.assertRaises(WorkflowEnvelopeError) as error:
            parse_operator_reviewed_workflow_envelope(payload)

        self.assertIn("executionId is required", str(error.exception))

    def test_rejects_hidden_shared_state_fields(self):
        payload = workflow_payload()
        payload["sharedState"] = {"cursor": "hidden"}

        with self.assertRaises(WorkflowEnvelopeError) as error:
            parse_operator_reviewed_workflow_envelope(payload)

        self.assertIn("hidden shared state", str(error.exception))
        self.assertIn("sharedState", str(error.exception))

    def test_rejects_ambiguous_multiple_handoffs(self):
        payload = workflow_payload()
        payload["handoffs"] = [handoff_payload(), handoff_payload()]

        with self.assertRaises(WorkflowEnvelopeError) as error:
            parse_operator_reviewed_workflow_envelope(payload)

        self.assertIn("handoffs", str(error.exception))

    def test_rejects_multi_symbiote_handoff_boundary(self):
        payload = workflow_payload()
        payload["handoff"]["symbiotes"] = [{"symbioteId": "symbiote-01"}]

        with self.assertRaises(WorkflowEnvelopeError) as error:
            parse_operator_reviewed_workflow_envelope(payload)

        self.assertIn("exactly one Symbiote", str(error.exception))

    def test_loads_workflow_envelope_from_json_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workflow.json"
            path.write_text(json.dumps(workflow_payload()), encoding="utf-8")

            envelope = load_operator_reviewed_workflow_envelope(path)

        self.assertEqual(envelope.source, str(path))
        self.assertEqual(envelope.evidence["issue"], "#246")

    def test_checked_in_example_stays_approval_required(self):
        envelope = load_operator_reviewed_workflow_envelope(EXAMPLE_PATH)

        self.assertFalse(envelope.safe_to_handoff)
        self.assertEqual(envelope.review.approval_state, "approval_required")
        self.assertEqual(envelope.evidence["routingEvidenceContract"], "docs/routing-evidence-contract.md")


if __name__ == "__main__":
    unittest.main()
