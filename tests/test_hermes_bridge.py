import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from furyoku import (
    ApprovalResumeLedger,
    ApprovalResumeRecord,
    HermesBridgeEnvelope,
    HermesBridgeError,
    HermesBridgeSevenSymbioteSmokeEnvelope,
    HermesBridgeThreeSymbioteSmokeEnvelope,
    ModelEndpoint,
    dry_run_hermes_bridge,
    dry_run_seven_symbiote_smoke,
    dry_run_three_symbiote_smoke,
    live_run_hermes_bridge,
    live_run_seven_symbiote_smoke,
    live_run_three_symbiote_smoke,
    load_hermes_bridge_envelope,
    load_hermes_seven_symbiote_smoke,
    load_hermes_three_symbiote_smoke,
)

ROOT = Path(__file__).resolve().parents[1]
SEVEN_SMOKE_ENVELOPE_PATH = ROOT / "examples" / "hermes_bridge_seven_symbiote.example.json"
SEVEN_SMOKE_APPROVAL_PATH = ROOT / "examples" / "hermes_approval_resume_seven_smoke.approved.json"


def local_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="local-echo",
        provider="local",
        privacy_level="local",
        context_window_tokens=4096,
        average_latency_ms=10,
        invocation=(sys.executable, "-c", "print('ready')"),
        capabilities={"conversation": 0.95, "instruction_following": 0.9},
    )


def cli_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="cli-fallback",
        provider="cli",
        privacy_level="remote",
        context_window_tokens=128000,
        average_latency_ms=20,
        invocation=("missing-cli-command",),
        capabilities={"conversation": 0.9, "instruction_following": 0.9},
    )


def seven_capable_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="local-seven-capable",
        provider="local",
        privacy_level="local",
        context_window_tokens=8192,
        average_latency_ms=10,
        invocation=(sys.executable, "-c", "print('ready')"),
        capabilities={
            "conversation": 0.95,
            "instruction_following": 0.9,
            "reasoning": 0.85,
            "retrieval": 0.8,
            "coding": 0.8,
            "summarization": 0.85,
            "safety": 0.8,
        },
    )


def envelope_payload() -> dict:
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
        "prompt": "Confirm the dry-run bridge.",
        "routing": {
            "checkHealth": True,
            "fallback": True,
            "maxAttempts": 2,
        },
    }


def approval_record_payload(
    execution_key: str,
    *,
    state: str = "approved",
    attempt_index: int = 1,
    workflow_id: str = "operator.reviewed.hermes-handoff",
    execution_id: str = "reviewed-handoff-001",
    owner: str = "furyoku-operator",
) -> dict:
    if state in {"resume_requested", "resume_approved", "resumed"} and attempt_index == 1:
        attempt_index = 2
    payload = {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "executionId": execution_id,
        "handoffExecutionKey": execution_key,
        "attemptIndex": attempt_index,
        "recordState": state,
        "owner": owner,
        "createdAtUtc": "2026-04-19T00:00:00Z",
        "evidence": {
            "workflowEnvelope": "docs/operator-reviewed-workflow-envelope.md",
            "issue": "#250",
        },
    }
    if state in {"approved", "resume_approved", "resumed"}:
        payload["approvedBy"] = "operator"
        payload["approvedAtUtc"] = "2026-04-19T01:00:00Z"
    if state in {"rejected", "duplicate_blocked", "stale_blocked"}:
        payload["reason"] = f"{state} by approval/resume gate test"
    if attempt_index > 1 or state in {"resume_requested", "resume_approved", "resumed"}:
        payload["resume"] = {
            "resumeOf": f"{workflow_id}:{execution_id}:{execution_key}",
            "previousAttemptIndex": attempt_index - 1,
            "requestedBy": "operator",
            "reason": "recoverable handoff retry",
        }
    return payload


def approval_record(execution_key: str, **overrides) -> ApprovalResumeRecord:
    return ApprovalResumeRecord.from_dict(approval_record_payload(execution_key, **overrides))


def approval_ledger(execution_keys: list[str] | tuple[str, ...], *, blocked_key: str | None = None) -> ApprovalResumeLedger:
    records = []
    for execution_key in execution_keys:
        state = "approval_pending" if execution_key == blocked_key else "approved"
        records.append(approval_record_payload(execution_key, state=state))
    return ApprovalResumeLedger.from_dict({"schemaVersion": 1, "records": records})


def three_symbiote_payload() -> dict:
    payloads = []
    for index, role in enumerate(("primary", "research", "synthesis"), start=1):
        payload = envelope_payload()
        payload["symbioteId"] = f"symbiote-{index:02d}"
        payload["role"] = role
        payload["task"]["taskId"] = f"hermes.bridge.three-symbiote.{role}"
        payload["prompt"] = f"Confirm the {role} three-Symbiote smoke handoff."
        payloads.append(payload)
    return {
        "schemaVersion": 1,
        "smokeId": "hermes.bridge.three-symbiote",
        "symbiotes": payloads,
    }


def seven_symbiote_payload() -> dict:
    role_capabilities = {
        "primary": {"conversation": 0.8, "instruction_following": 0.8},
        "planning": {"conversation": 0.8, "instruction_following": 0.8, "reasoning": 0.6},
        "research": {"conversation": 0.8, "instruction_following": 0.8, "retrieval": 0.6},
        "implementation": {"conversation": 0.8, "instruction_following": 0.8, "coding": 0.6},
        "verification": {"conversation": 0.8, "instruction_following": 0.8, "reasoning": 0.6},
        "synthesis": {"conversation": 0.8, "instruction_following": 0.8, "summarization": 0.6},
        "guard": {"conversation": 0.8, "instruction_following": 0.8, "safety": 0.6},
    }
    payloads = []
    for index, (role, capabilities) in enumerate(role_capabilities.items(), start=1):
        payload = envelope_payload()
        payload["symbioteId"] = f"symbiote-{index:02d}"
        payload["role"] = role
        payload["task"]["taskId"] = f"hermes.bridge.seven-symbiote.{role}"
        payload["task"]["requiredCapabilities"] = capabilities
        payload["prompt"] = f"Confirm the {role} seven-Symbiote smoke handoff."
        payloads.append(payload)
    return {
        "schemaVersion": 1,
        "smokeId": "hermes.bridge.seven-symbiote",
        "symbiotes": payloads,
    }


class HermesBridgeTests(unittest.TestCase):
    def test_loads_one_symbiote_envelope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "envelope.json"
            path.write_text(json.dumps(envelope_payload()), encoding="utf-8")

            envelope = load_hermes_bridge_envelope(path)

        self.assertEqual(envelope.symbiote_id, "symbiote-01")
        self.assertEqual(envelope.role, "primary")
        self.assertEqual(envelope.task.task_id, "hermes.bridge.one-symbiote")
        self.assertEqual(envelope.execution_key, "symbiote-01:primary:hermes.bridge.one-symbiote")
        self.assertTrue(envelope.routing.check_health)
        self.assertEqual(envelope.routing.max_attempts, 2)

    def test_rejects_multi_symbiote_payload(self):
        payload = envelope_payload()
        payload["symbiotes"] = [{"symbioteId": "symbiote-01"}, {"symbioteId": "symbiote-02"}]

        with self.assertRaises(HermesBridgeError) as error:
            HermesBridgeEnvelope.from_dict(payload)

        self.assertIn("exactly one Symbiote", str(error.exception))

    def test_dry_run_selects_model_and_does_not_start_execution(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())

        result = dry_run_hermes_bridge(
            [local_endpoint(), cli_endpoint()],
            envelope,
            command_resolver=lambda command: command if command == sys.executable else None,
        )
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["selectedModel"]["modelId"], "local-echo")
        self.assertEqual(payload["handoff"]["status"], "dry-run-ready")
        self.assertEqual(payload["execution"]["status"], "not-started")
        self.assertFalse(payload["execution"]["started"])
        self.assertEqual(payload["duplicateGuard"]["executionKey"], envelope.execution_key)
        self.assertTrue(any(item["modelId"] == "local-echo" and item["ready"] for item in payload["readiness"]))

    def test_dry_run_prevents_duplicate_execution_key(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())

        result = dry_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            seen_execution_keys=[envelope.execution_key],
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "duplicate-prevented")
        self.assertEqual(payload["execution"]["status"], "skipped")
        self.assertTrue(payload["duplicateGuard"]["duplicate"])
        self.assertEqual(payload["error"]["code"], "duplicate_execution_key")

    def test_dry_run_reports_recoverable_routing_blocker(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        weak_model = ModelEndpoint(
            model_id="weak-local",
            provider="local",
            privacy_level="local",
            context_window_tokens=4096,
            average_latency_ms=10,
            invocation=(sys.executable,),
            capabilities={"conversation": 0.2},
        )

        result = dry_run_hermes_bridge([weak_model], envelope)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "routing-blocked")
        self.assertEqual(payload["error"]["code"], "no_eligible_model")
        self.assertIn("instruction_following", payload["error"]["message"])

    def test_live_run_invokes_one_handoff_command(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        result = live_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            approval_resume=approval_record(envelope.execution_key),
            require_approval_resume=True,
            handoff_command=(
                sys.executable,
                "-c",
                "import json, sys; payload=json.load(sys.stdin); print(json.dumps({'status':'ok','executionKey':payload['envelope']['executionKey'],'approvalGate':payload['approvalResumeGate']['status']}))",
            ),
        )
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["handoff"]["status"], "completed")
        self.assertEqual(payload["execution"]["status"], "succeeded")
        self.assertTrue(payload["execution"]["started"])
        self.assertEqual(payload["execution"]["runtimePayload"]["executionKey"], envelope.execution_key)
        self.assertEqual(payload["approvalResumeGate"]["status"], "approved")
        self.assertEqual(payload["execution"]["runtimePayload"]["approvalGate"], "approved")

    def test_live_run_requires_approval_record_when_gate_is_required(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        result = live_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            require_approval_resume=True,
            handoff_command=(sys.executable, "-c", "import sys; sys.exit(99)"),
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "approval-blocked")
        self.assertEqual(payload["execution"]["status"], "not-started")
        self.assertFalse(payload["execution"]["started"])
        self.assertEqual(payload["approvalResumeGate"]["status"], "blocked")
        self.assertEqual(payload["error"]["code"], "approval_resume_record_missing")

    def test_live_run_blocks_unsafe_approval_resume_states_before_handoff(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        blocked_states = (
            "approval_pending",
            "rejected",
            "resume_requested",
            "resumed",
            "duplicate_blocked",
            "stale_blocked",
        )

        for state in blocked_states:
            with self.subTest(state=state):
                result = live_run_hermes_bridge(
                    [local_endpoint()],
                    envelope,
                    approval_resume=approval_record(envelope.execution_key, state=state),
                    require_approval_resume=True,
                    handoff_command=(sys.executable, "-c", "import sys; sys.exit(99)"),
                )
                payload = result.to_dict()

                self.assertFalse(result.ok)
                self.assertEqual(payload["handoff"]["status"], "approval-blocked")
                self.assertEqual(payload["execution"]["status"], "not-started")
                self.assertFalse(payload["execution"]["started"])
                self.assertEqual(payload["approvalResumeGate"]["recordState"], state)
                self.assertEqual(payload["error"]["code"], "approval_resume_not_safe")

    def test_live_run_blocks_mismatched_approval_record_before_handoff(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        result = live_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            approval_resume=approval_record("symbiote-99:other:wrong-task"),
            require_approval_resume=True,
            handoff_command=(sys.executable, "-c", "import sys; sys.exit(99)"),
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "approval-blocked")
        self.assertFalse(payload["execution"]["started"])
        self.assertEqual(payload["error"]["code"], "approval_resume_handoff_mismatch")

    def test_live_run_ledger_uses_latest_resume_approval(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        ledger = ApprovalResumeLedger.from_dict(
            {
                "schemaVersion": 1,
                "records": [
                    approval_record_payload(envelope.execution_key, state="approved"),
                    approval_record_payload(envelope.execution_key, state="resume_approved", attempt_index=2),
                ],
            }
        )
        result = live_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            approval_resume=ledger,
            require_approval_resume=True,
            handoff_command=(
                sys.executable,
                "-c",
                "import json, sys; payload=json.load(sys.stdin); print(json.dumps({'gate':payload['approvalResumeGate']['status'],'attempt':payload['approvalResumeGate']['attemptIndex']}))",
            ),
        )
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["approvalResumeGate"]["status"], "resume-approved")
        self.assertEqual(payload["approvalResumeGate"]["attemptIndex"], 2)
        self.assertEqual(payload["execution"]["runtimePayload"]["gate"], "resume-approved")

    def test_live_run_ledger_blocks_latest_resume_request(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        ledger = ApprovalResumeLedger.from_dict(
            {
                "schemaVersion": 1,
                "records": [
                    approval_record_payload(envelope.execution_key, state="approved"),
                    approval_record_payload(envelope.execution_key, state="resume_requested", attempt_index=2),
                ],
            }
        )
        result = live_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            approval_resume=ledger,
            require_approval_resume=True,
            handoff_command=(sys.executable, "-c", "import sys; sys.exit(99)"),
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "approval-blocked")
        self.assertFalse(payload["execution"]["started"])
        self.assertEqual(payload["approvalResumeGate"]["recordState"], "resume_requested")

    def test_live_run_does_not_start_duplicate_execution_key(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        result = live_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            handoff_command=("missing-live-handoff-command",),
            seen_execution_keys=[envelope.execution_key],
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "duplicate-prevented")
        self.assertEqual(payload["execution"]["status"], "skipped")
        self.assertFalse(payload["execution"]["started"])
        self.assertTrue(payload["duplicateGuard"]["duplicate"])

    def test_live_run_reports_recoverable_handoff_failure(self):
        envelope = HermesBridgeEnvelope.from_dict(envelope_payload())
        result = live_run_hermes_bridge(
            [local_endpoint()],
            envelope,
            handoff_command=(sys.executable, "-c", "import sys; sys.stderr.write('bad runtime'); sys.exit(3)"),
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "failed")
        self.assertEqual(payload["execution"]["status"], "error")
        self.assertEqual(payload["execution"]["exitCode"], 3)
        self.assertEqual(payload["error"]["code"], "handoff_process_failed")

    def test_loads_three_symbiote_smoke_envelope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "three-smoke.json"
            path.write_text(json.dumps(three_symbiote_payload()), encoding="utf-8")

            envelope = load_hermes_three_symbiote_smoke(path)

        self.assertEqual(envelope.smoke_id, "hermes.bridge.three-symbiote")
        self.assertEqual(len(envelope.symbiotes), 3)
        self.assertEqual(
            envelope.execution_keys,
            (
                "symbiote-01:primary:hermes.bridge.three-symbiote.primary",
                "symbiote-02:research:hermes.bridge.three-symbiote.research",
                "symbiote-03:synthesis:hermes.bridge.three-symbiote.synthesis",
            ),
        )

    def test_three_symbiote_smoke_requires_exactly_three_symbiotes(self):
        payload = three_symbiote_payload()
        payload["symbiotes"] = payload["symbiotes"][:2]

        with self.assertRaises(HermesBridgeError) as error:
            HermesBridgeThreeSymbioteSmokeEnvelope.from_dict(payload)

        self.assertIn("exactly three Symbiotes", str(error.exception))

    def test_three_symbiote_dry_run_routes_three_distinct_handoffs(self):
        envelope = HermesBridgeThreeSymbioteSmokeEnvelope.from_dict(three_symbiote_payload())

        result = dry_run_three_symbiote_smoke(
            [local_endpoint(), cli_endpoint()],
            envelope,
            command_resolver=lambda command: command if command == sys.executable else None,
        )
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["handoff"]["status"], "dry-run-ready")
        self.assertEqual(payload["execution"]["status"], "not-started")
        self.assertEqual(payload["aggregate"]["totalSymbiotes"], 3)
        self.assertEqual(payload["aggregate"]["succeeded"], 3)
        self.assertEqual(payload["duplicateGuard"]["duplicates"], [])
        self.assertEqual([item["selectedModel"]["modelId"] for item in payload["results"]], ["local-echo"] * 3)

    def test_three_symbiote_dry_run_prevents_duplicate_execution_key(self):
        payload = three_symbiote_payload()
        payload["symbiotes"][1]["symbioteId"] = payload["symbiotes"][0]["symbioteId"]
        payload["symbiotes"][1]["role"] = payload["symbiotes"][0]["role"]
        payload["symbiotes"][1]["task"]["taskId"] = payload["symbiotes"][0]["task"]["taskId"]
        envelope = HermesBridgeThreeSymbioteSmokeEnvelope.from_dict(payload)

        result = dry_run_three_symbiote_smoke([local_endpoint()], envelope)
        report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(report["aggregate"]["duplicatesPrevented"], 1)
        self.assertEqual(report["results"][1]["handoff"]["status"], "duplicate-prevented")
        self.assertFalse(report["results"][1]["execution"]["started"])
        self.assertEqual(report["error"]["code"], "three_symbiote_smoke_incomplete")

    def test_three_symbiote_live_run_invokes_ordered_handoffs(self):
        envelope = HermesBridgeThreeSymbioteSmokeEnvelope.from_dict(three_symbiote_payload())
        result = live_run_three_symbiote_smoke(
            [local_endpoint()],
            envelope,
            approval_resume=approval_ledger(envelope.execution_keys),
            require_approval_resume=True,
            handoff_command=(
                sys.executable,
                "-c",
                "import json, sys; payload=json.load(sys.stdin); print(json.dumps({'status':'ok','executionKey':payload['envelope']['executionKey']}))",
            ),
        )
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["handoff"]["status"], "completed")
        self.assertEqual(payload["execution"]["status"], "succeeded")
        self.assertEqual(payload["aggregate"]["succeeded"], 3)
        self.assertTrue(payload["approvalResumeGate"]["required"])
        self.assertEqual(payload["approvalResumeGate"]["blockedExecutionKeys"], [])
        self.assertEqual(
            [item["execution"]["runtimePayload"]["executionKey"] for item in payload["results"]],
            list(envelope.execution_keys),
        )
        self.assertEqual(
            [item["approvalResumeGate"]["status"] for item in payload["results"]],
            ["approved", "approved", "approved"],
        )

    def test_three_symbiote_live_run_blocks_pending_ledger_record_before_handoff(self):
        envelope = HermesBridgeThreeSymbioteSmokeEnvelope.from_dict(three_symbiote_payload())
        blocked_key = envelope.execution_keys[1]
        result = live_run_three_symbiote_smoke(
            [local_endpoint()],
            envelope,
            approval_resume=approval_ledger(envelope.execution_keys, blocked_key=blocked_key),
            require_approval_resume=True,
            handoff_command=(
                sys.executable,
                "-c",
                "import json, sys; payload=json.load(sys.stdin); key=payload['envelope']['executionKey']; sys.exit(99) if key.endswith('.research') else print(json.dumps({'executionKey':key}))",
            ),
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["handoff"]["status"], "partial")
        self.assertEqual(payload["execution"]["status"], "partial")
        self.assertEqual(payload["approvalResumeGate"]["blockedExecutionKeys"], [blocked_key])
        self.assertEqual(payload["results"][1]["handoff"]["status"], "approval-blocked")
        self.assertFalse(payload["results"][1]["execution"]["started"])
        self.assertEqual(payload["results"][1]["error"]["code"], "approval_resume_not_safe")
        self.assertEqual(payload["results"][2]["handoff"]["status"], "completed")

    def test_loads_seven_symbiote_smoke_envelope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "seven-smoke.json"
            path.write_text(json.dumps(seven_symbiote_payload()), encoding="utf-8")

            envelope = load_hermes_seven_symbiote_smoke(path)

        self.assertEqual(envelope.smoke_id, "hermes.bridge.seven-symbiote")
        self.assertEqual(len(envelope.symbiotes), 7)
        self.assertEqual(envelope.execution_keys[0], "symbiote-01:primary:hermes.bridge.seven-symbiote.primary")
        self.assertEqual(envelope.execution_keys[-1], "symbiote-07:guard:hermes.bridge.seven-symbiote.guard")

    def test_seven_symbiote_smoke_requires_exactly_seven_symbiotes(self):
        payload = seven_symbiote_payload()
        payload["symbiotes"] = payload["symbiotes"][:6]

        with self.assertRaises(HermesBridgeError) as error:
            HermesBridgeSevenSymbioteSmokeEnvelope.from_dict(payload)

        self.assertIn("exactly 7 Symbiotes", str(error.exception))

    def test_seven_symbiote_dry_run_routes_seven_distinct_handoffs(self):
        envelope = HermesBridgeSevenSymbioteSmokeEnvelope.from_dict(seven_symbiote_payload())

        result = dry_run_seven_symbiote_smoke(
            [seven_capable_endpoint(), cli_endpoint()],
            envelope,
            command_resolver=lambda command: command if command == sys.executable else None,
        )
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["handoff"]["status"], "dry-run-ready")
        self.assertEqual(payload["execution"]["status"], "not-started")
        self.assertEqual(payload["aggregate"]["totalSymbiotes"], 7)
        self.assertEqual(payload["aggregate"]["succeeded"], 7)
        self.assertEqual(payload["duplicateGuard"]["duplicates"], [])
        self.assertEqual(len(payload["results"]), 7)

    def test_seven_symbiote_dry_run_prevents_duplicate_execution_key(self):
        payload = seven_symbiote_payload()
        payload["symbiotes"][6]["symbioteId"] = payload["symbiotes"][0]["symbioteId"]
        payload["symbiotes"][6]["role"] = payload["symbiotes"][0]["role"]
        payload["symbiotes"][6]["task"]["taskId"] = payload["symbiotes"][0]["task"]["taskId"]
        envelope = HermesBridgeSevenSymbioteSmokeEnvelope.from_dict(payload)

        result = dry_run_seven_symbiote_smoke([seven_capable_endpoint()], envelope)
        report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(report["aggregate"]["duplicatesPrevented"], 1)
        self.assertEqual(report["results"][6]["handoff"]["status"], "duplicate-prevented")
        self.assertFalse(report["results"][6]["execution"]["started"])
        self.assertEqual(report["error"]["code"], "seven_symbiote_smoke_incomplete")

    def test_seven_symbiote_live_run_invokes_ordered_handoffs(self):
        envelope = HermesBridgeSevenSymbioteSmokeEnvelope.from_dict(seven_symbiote_payload())
        result = live_run_seven_symbiote_smoke(
            [seven_capable_endpoint()],
            envelope,
            approval_resume=approval_ledger(envelope.execution_keys),
            require_approval_resume=True,
            handoff_command=(
                sys.executable,
                "-c",
                "import json, sys; payload=json.load(sys.stdin); print(json.dumps({'status':'ok','executionKey':payload['envelope']['executionKey']}))",
            ),
        )
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["handoff"]["status"], "completed")
        self.assertEqual(payload["execution"]["status"], "succeeded")
        self.assertEqual(payload["aggregate"]["succeeded"], 7)
        self.assertTrue(payload["approvalResumeGate"]["required"])
        self.assertEqual(payload["approvalResumeGate"]["blockedExecutionKeys"], [])
        self.assertEqual(
            [item["execution"]["runtimePayload"]["executionKey"] for item in payload["results"]],
            list(envelope.execution_keys),
        )


class HermesBridgeCliTests(unittest.TestCase):
    def test_cli_dry_run_outputs_bridge_report(self):
        from furyoku.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "envelope.json"
            registry_path.write_text(
                json.dumps(
                    {
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
                                    "import sys; print(sys.stdin.read())",
                                ],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(envelope_payload()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "furyoku.cli",
                    "hermes-bridge",
                    "--registry",
                    str(registry_path),
                    "--envelope",
                    str(envelope_path),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["bridge"], "hermes-furyoku")
        self.assertEqual(payload["selectedModel"]["modelId"], "local-echo")
        self.assertEqual(payload["handoff"]["status"], "dry-run-ready")

    def test_cli_requires_dry_run_flag(self):
        from furyoku.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "envelope.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [sys.executable],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(envelope_payload()), encoding="utf-8")

            with redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(
                        [
                            "hermes-bridge",
                            "--registry",
                            str(registry_path),
                            "--envelope",
                            str(envelope_path),
                        ]
                    )

        self.assertEqual(error.exception.code, 2)

    def test_cli_live_mode_invokes_handoff_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "envelope.json"
            approval_path = temp_path / "approval.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [sys.executable, "-c", "print('ready')"],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(envelope_payload()), encoding="utf-8")
            approval_path.write_text(
                json.dumps(approval_record_payload("symbiote-01:primary:hermes.bridge.one-symbiote")),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "furyoku.cli",
                    "hermes-bridge",
                    "--registry",
                    str(registry_path),
                    "--envelope",
                    str(envelope_path),
                    "--timeout-seconds",
                    "5",
                    "--approval-resume-record",
                    str(approval_path),
                    "--require-approval-resume",
                    "--handoff-command",
                    sys.executable,
                    "-c",
                    "import json, sys; payload=json.load(sys.stdin); print(json.dumps({'received':payload['envelope']['executionKey']}))",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["handoff"]["status"], "completed")
        self.assertEqual(payload["approvalResumeGate"]["status"], "approved")
        self.assertEqual(payload["execution"]["runtimePayload"]["received"], "symbiote-01:primary:hermes.bridge.one-symbiote")

    def test_cli_live_mode_blocks_pending_approval_before_handoff_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "envelope.json"
            approval_path = temp_path / "approval-pending.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [sys.executable, "-c", "print('ready')"],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(envelope_payload()), encoding="utf-8")
            approval_path.write_text(
                json.dumps(
                    approval_record_payload(
                        "symbiote-01:primary:hermes.bridge.one-symbiote",
                        state="approval_pending",
                    )
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "furyoku.cli",
                    "hermes-bridge",
                    "--registry",
                    str(registry_path),
                    "--envelope",
                    str(envelope_path),
                    "--approval-resume-record",
                    str(approval_path),
                    "--require-approval-resume",
                    "--handoff-command",
                    sys.executable,
                    "-c",
                    "import sys; sys.exit(99)",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["handoff"]["status"], "approval-blocked")
        self.assertEqual(payload["execution"]["status"], "not-started")
        self.assertFalse(payload["execution"]["started"])
        self.assertEqual(payload["approvalResumeGate"]["recordState"], "approval_pending")

    def test_cli_three_symbiote_dry_run_outputs_aggregate_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "three-smoke.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [sys.executable, "-c", "print('ready')"],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(three_symbiote_payload()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "furyoku.cli",
                    "hermes-three-smoke",
                    "--registry",
                    str(registry_path),
                    "--envelope",
                    str(envelope_path),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["bridge"], "hermes-furyoku")
        self.assertEqual(payload["smoke"]["symbioteCount"], 3)
        self.assertEqual(payload["aggregate"]["succeeded"], 3)
        self.assertEqual(len(payload["results"]), 3)

    def test_cli_three_symbiote_live_mode_accepts_approval_ledger(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "three-smoke.json"
            ledger_path = temp_path / "approval-ledger.json"
            smoke_payload = three_symbiote_payload()
            envelope = HermesBridgeThreeSymbioteSmokeEnvelope.from_dict(smoke_payload)
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [sys.executable, "-c", "print('ready')"],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(smoke_payload), encoding="utf-8")
            ledger_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "records": [
                            approval_record_payload(execution_key)
                            for execution_key in envelope.execution_keys
                        ],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "furyoku.cli",
                    "hermes-three-smoke",
                    "--registry",
                    str(registry_path),
                    "--envelope",
                    str(envelope_path),
                    "--approval-resume-ledger",
                    str(ledger_path),
                    "--require-approval-resume",
                    "--handoff-command",
                    sys.executable,
                    "-c",
                    "import json, sys; payload=json.load(sys.stdin); print(json.dumps({'received':payload['envelope']['executionKey']}))",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["aggregate"]["succeeded"], 3)
        self.assertTrue(payload["approvalResumeGate"]["required"])
        self.assertEqual(payload["approvalResumeGate"]["blockedExecutionKeys"], [])

    def test_cli_seven_symbiote_dry_run_outputs_aggregate_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry_path = temp_path / "models.json"
            envelope_path = temp_path / "seven-smoke.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [sys.executable, "-c", "print('ready')"],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                    "reasoning": 0.8,
                                    "retrieval": 0.8,
                                    "coding": 0.8,
                                    "summarization": 0.8,
                                    "safety": 0.8,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            envelope_path.write_text(json.dumps(seven_symbiote_payload()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "furyoku.cli",
                    "hermes-seven-smoke",
                    "--registry",
                    str(registry_path),
                    "--envelope",
                    str(envelope_path),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["bridge"], "hermes-furyoku")
        self.assertEqual(payload["smoke"]["symbioteCount"], 7)
        self.assertEqual(payload["aggregate"]["succeeded"], 7)
        self.assertEqual(len(payload["results"]), 7)

    def test_cli_seven_symbiote_live_mode_accepts_checked_in_approval_ledger(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "models.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [sys.executable, "-c", "print('ready')"],
                                "capabilities": {
                                    "conversation": 0.95,
                                    "instruction_following": 0.9,
                                    "reasoning": 0.8,
                                    "retrieval": 0.8,
                                    "coding": 0.8,
                                    "summarization": 0.8,
                                    "safety": 0.8,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "furyoku.cli",
                    "hermes-seven-smoke",
                    "--registry",
                    str(registry_path),
                    "--envelope",
                    str(SEVEN_SMOKE_ENVELOPE_PATH),
                    "--approval-resume-ledger",
                    str(SEVEN_SMOKE_APPROVAL_PATH),
                    "--require-approval-resume",
                    "--handoff-command",
                    sys.executable,
                    "-c",
                    "import json, sys; payload=json.load(sys.stdin); print(json.dumps({'received':payload['envelope']['executionKey'],'gate':payload['approvalResumeGate']['status']}))",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["aggregate"]["succeeded"], 7)
        self.assertTrue(payload["approvalResumeGate"]["required"])
        self.assertEqual(payload["approvalResumeGate"]["blockedExecutionKeys"], [])
        self.assertEqual(
            [item["execution"]["runtimePayload"]["gate"] for item in payload["results"]],
            ["approved"] * 7,
        )
