from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .hermes_bridge import HermesBridgeEnvelope, HermesBridgeError


class WorkflowEnvelopeError(ValueError):
    """Raised when an operator-reviewed Hermes workflow envelope is malformed."""


APPROVAL_STATES = frozenset({"approval_required", "approved", "rejected"})
FORBIDDEN_ROOT_FIELDS = frozenset(
    {
        "cache",
        "conversationHistory",
        "globalState",
        "handoffCommand",
        "handoffs",
        "memory",
        "resumeState",
        "scheduler",
        "secrets",
        "sharedState",
        "state",
        "symbiotes",
        "tasks",
        "workflowRuntime",
    }
)


@dataclass(frozen=True)
class OperatorReview:
    """Explicit operator approval boundary for one Hermes/FURYOKU handoff."""

    approval_state: str
    requested_by: str = ""
    approved_by: str | None = None
    approved_at_utc: str | None = None
    reason: str = ""

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def approval_required(self) -> bool:
        return self.approval_state == "approval_required"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str = "<memory>") -> "OperatorReview":
        if not isinstance(payload, Mapping):
            raise WorkflowEnvelopeError(f"{source}: review must be a JSON object")
        approval_state = _required_string(payload, "approvalState", "approval_state", source=source)
        if approval_state not in APPROVAL_STATES:
            allowed = ", ".join(sorted(APPROVAL_STATES))
            raise WorkflowEnvelopeError(f"{source}: review.approvalState must be one of {allowed}")
        approved_by = _optional_string(payload, "approvedBy", "approved_by")
        approved_at_utc = _optional_string(payload, "approvedAtUtc", "approved_at_utc")
        reason = _optional_string(payload, "reason") or ""
        if approval_state == "approved" and not approved_by:
            raise WorkflowEnvelopeError(f"{source}: approved review requires review.approvedBy")
        if approval_state == "rejected" and not reason:
            raise WorkflowEnvelopeError(f"{source}: rejected review requires review.reason")
        return cls(
            approval_state=approval_state,
            requested_by=_optional_string(payload, "requestedBy", "requested_by") or "",
            approved_by=approved_by,
            approved_at_utc=approved_at_utc,
            reason=reason,
        )

    def to_dict(self) -> dict:
        return {
            "approvalState": self.approval_state,
            "approvalRequired": self.approval_required,
            "approved": self.approved,
            "requestedBy": self.requested_by,
            "approvedBy": self.approved_by,
            "approvedAtUtc": self.approved_at_utc,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OperatorReviewedHermesWorkflowEnvelope:
    """A FURYOKU-owned typed envelope for one operator-reviewed Hermes handoff."""

    schema_version: int
    workflow_id: str
    execution_id: str
    review: OperatorReview
    handoff: HermesBridgeEnvelope
    created_at_utc: str = ""
    evidence: Mapping[str, str] = field(default_factory=dict)
    source: str = "<memory>"

    @property
    def workflow_execution_key(self) -> str:
        return f"{self.workflow_id}:{self.execution_id}:{self.handoff.execution_key}"

    @property
    def safe_to_handoff(self) -> bool:
        return self.review.approved

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        source: str = "<memory>",
    ) -> "OperatorReviewedHermesWorkflowEnvelope":
        if not isinstance(payload, Mapping):
            raise WorkflowEnvelopeError(f"{source}: workflow envelope must be a JSON object")
        _reject_forbidden_root_fields(payload, source=source)
        schema_version = _schema_version(payload, source=source)
        workflow_id = _required_string(payload, "workflowId", "workflow_id", source=source)
        execution_id = _required_string(payload, "executionId", "execution_id", source=source)

        raw_handoff = payload.get("handoff")
        if not isinstance(raw_handoff, Mapping):
            raise WorkflowEnvelopeError(f"{source}: handoff must be a JSON object")
        try:
            handoff = HermesBridgeEnvelope.from_dict(raw_handoff, source=f"{source}:handoff")
        except HermesBridgeError as exc:
            raise WorkflowEnvelopeError(str(exc)) from exc

        return cls(
            schema_version=schema_version,
            workflow_id=workflow_id,
            execution_id=execution_id,
            review=OperatorReview.from_dict(payload.get("review", {}), source=f"{source}:review"),
            handoff=handoff,
            created_at_utc=_optional_string(payload, "createdAtUtc", "created_at_utc") or "",
            evidence=_evidence_mapping(payload.get("evidence", {}), source=f"{source}:evidence"),
            source=source,
        )

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "workflowId": self.workflow_id,
            "executionId": self.execution_id,
            "workflowExecutionKey": self.workflow_execution_key,
            "createdAtUtc": self.created_at_utc,
            "safeToHandoff": self.safe_to_handoff,
            "review": self.review.to_dict(),
            "handoff": self.handoff.to_dict(),
            "evidence": dict(self.evidence),
            "guardrails": {
                "singleHandoff": True,
                "operatorApprovalRequired": not self.safe_to_handoff,
                "hiddenSharedStateAllowed": False,
                "runtimeOwner": "Hermes-derived FURYOKU",
                "modelSelectionOwner": "FURYOKU routing/provider health",
            },
        }


def load_operator_reviewed_workflow_envelope(path: str | Path) -> OperatorReviewedHermesWorkflowEnvelope:
    envelope_path = Path(path)
    with envelope_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return parse_operator_reviewed_workflow_envelope(payload, source=str(envelope_path))


def parse_operator_reviewed_workflow_envelope(
    payload: Mapping[str, Any],
    *,
    source: str = "<memory>",
) -> OperatorReviewedHermesWorkflowEnvelope:
    return OperatorReviewedHermesWorkflowEnvelope.from_dict(payload, source=source)


def _schema_version(payload: Mapping[str, Any], *, source: str) -> int:
    raw_version = payload.get("schemaVersion", payload.get("schema_version", 1))
    try:
        schema_version = int(raw_version or 1)
    except (TypeError, ValueError) as exc:
        raise WorkflowEnvelopeError(f"{source}: schemaVersion must be an integer") from exc
    if schema_version != 1:
        raise WorkflowEnvelopeError(f"{source}: unsupported workflow envelope schemaVersion {schema_version!r}")
    return schema_version


def _reject_forbidden_root_fields(payload: Mapping[str, Any], *, source: str) -> None:
    forbidden = sorted(key for key in payload if key in FORBIDDEN_ROOT_FIELDS)
    if forbidden:
        names = ", ".join(forbidden)
        raise WorkflowEnvelopeError(f"{source}: workflow envelope may not carry hidden shared state or scheduler fields: {names}")


def _evidence_mapping(value: Any, *, source: str) -> Mapping[str, str]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise WorkflowEnvelopeError(f"{source}: evidence must be a JSON object")
    evidence: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str) or not item.strip():
            raise WorkflowEnvelopeError(f"{source}: evidence.{key} must be a non-empty string")
        evidence[str(key)] = item.strip()
    return evidence


def _required_string(payload: Mapping[str, Any], *keys: str, source: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise WorkflowEnvelopeError(f"{source}: {keys[0]} is required")


def _optional_string(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
