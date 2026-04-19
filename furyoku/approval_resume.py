from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .workflow_envelope import OperatorReviewedHermesWorkflowEnvelope, WorkflowEnvelopeError


class ApprovalResumeError(ValueError):
    """Raised when approval/resume records cannot be trusted for handoff control."""


APPROVAL_RESUME_STATES = frozenset(
    {
        "approval_pending",
        "approved",
        "rejected",
        "resume_requested",
        "resume_approved",
        "resumed",
        "duplicate_blocked",
        "stale_blocked",
    }
)
RESUME_STATES = frozenset({"resume_requested", "resume_approved", "resumed"})
SAFE_TO_HANDOFF_STATES = frozenset({"approved", "resume_approved"})
FORBIDDEN_RECORD_FIELDS = frozenset(
    {
        "cache",
        "conversationHistory",
        "globalState",
        "handoffCommand",
        "handoffs",
        "memory",
        "owners",
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
class ResumeIntent:
    """Explicit operator intent to replay a prior workflow execution key."""

    resume_of: str
    previous_attempt_index: int
    requested_by: str
    reason: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str = "<memory>") -> "ResumeIntent":
        if not isinstance(payload, Mapping):
            raise ApprovalResumeError(f"{source}: resume must be a JSON object")
        return cls(
            resume_of=_required_string(payload, "resumeOf", "resume_of", source=source),
            previous_attempt_index=_positive_int(
                payload.get("previousAttemptIndex", payload.get("previous_attempt_index")),
                field_name="previousAttemptIndex",
                source=source,
            ),
            requested_by=_required_string(payload, "requestedBy", "requested_by", source=source),
            reason=_required_string(payload, "reason", source=source),
        )

    def to_dict(self) -> dict:
        return {
            "resumeOf": self.resume_of,
            "previousAttemptIndex": self.previous_attempt_index,
            "requestedBy": self.requested_by,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ApprovalResumeRecord:
    """One execution-keyed approval or resume decision for a Hermes/FURYOKU handoff."""

    schema_version: int
    workflow_id: str
    execution_id: str
    handoff_execution_key: str
    state: str
    owner: str
    attempt_index: int = 1
    approved_by: str | None = None
    approved_at_utc: str | None = None
    reason: str = ""
    resume: ResumeIntent | None = None
    created_at_utc: str = ""
    evidence: Mapping[str, str] = field(default_factory=dict)
    source: str = "<memory>"

    @property
    def workflow_execution_key(self) -> str:
        return f"{self.workflow_id}:{self.execution_id}:{self.handoff_execution_key}"

    @property
    def record_key(self) -> str:
        return f"{self.workflow_execution_key}:attempt:{self.attempt_index}"

    @property
    def safe_to_handoff(self) -> bool:
        return self.state in SAFE_TO_HANDOFF_STATES

    @property
    def is_resume(self) -> bool:
        return self.resume is not None or self.state in RESUME_STATES

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str = "<memory>") -> "ApprovalResumeRecord":
        if not isinstance(payload, Mapping):
            raise ApprovalResumeError(f"{source}: approval/resume record must be a JSON object")
        _reject_forbidden_record_fields(payload, source=source)
        schema_version = _schema_version(payload, source=source)
        state = _required_string(payload, "recordState", "stateName", source=source)
        if state not in APPROVAL_RESUME_STATES:
            allowed = ", ".join(sorted(APPROVAL_RESUME_STATES))
            raise ApprovalResumeError(f"{source}: recordState must be one of {allowed}")

        attempt_index = _positive_int(
            payload.get("attemptIndex", payload.get("attempt_index", 1)),
            field_name="attemptIndex",
            source=source,
        )
        resume = _optional_resume_intent(payload.get("resume"), source=f"{source}:resume")
        record = cls(
            schema_version=schema_version,
            workflow_id=_required_string(payload, "workflowId", "workflow_id", source=source),
            execution_id=_required_string(payload, "executionId", "execution_id", source=source),
            handoff_execution_key=_required_string(
                payload,
                "handoffExecutionKey",
                "handoff_execution_key",
                source=source,
            ),
            state=state,
            owner=_required_string(payload, "owner", source=source),
            attempt_index=attempt_index,
            approved_by=_optional_string(payload, "approvedBy", "approved_by"),
            approved_at_utc=_optional_string(payload, "approvedAtUtc", "approved_at_utc"),
            reason=_optional_string(payload, "reason") or "",
            resume=resume,
            created_at_utc=_optional_string(payload, "createdAtUtc", "created_at_utc") or "",
            evidence=_evidence_mapping(payload.get("evidence", {}), source=f"{source}:evidence"),
            source=source,
        )
        record._validate()
        return record

    @classmethod
    def from_workflow_envelope(
        cls,
        envelope: OperatorReviewedHermesWorkflowEnvelope,
        *,
        owner: str,
        source: str = "<workflow-envelope>",
    ) -> "ApprovalResumeRecord":
        if envelope.review.approval_state == "approval_required":
            state = "approval_pending"
        elif envelope.review.approval_state == "approved":
            state = "approved"
        else:
            state = "rejected"
        record = cls(
            schema_version=1,
            workflow_id=envelope.workflow_id,
            execution_id=envelope.execution_id,
            handoff_execution_key=envelope.handoff.execution_key,
            state=state,
            owner=owner,
            approved_by=envelope.review.approved_by,
            approved_at_utc=envelope.review.approved_at_utc,
            reason=envelope.review.reason,
            created_at_utc=envelope.created_at_utc,
            evidence=dict(envelope.evidence),
            source=source,
        )
        record._validate()
        return record

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "workflowId": self.workflow_id,
            "executionId": self.execution_id,
            "handoffExecutionKey": self.handoff_execution_key,
            "workflowExecutionKey": self.workflow_execution_key,
            "recordKey": self.record_key,
            "attemptIndex": self.attempt_index,
            "recordState": self.state,
            "owner": self.owner,
            "safeToHandoff": self.safe_to_handoff,
            "resumable": self.is_resume,
            "approvedBy": self.approved_by,
            "approvedAtUtc": self.approved_at_utc,
            "reason": self.reason,
            "resume": self.resume.to_dict() if self.resume is not None else None,
            "createdAtUtc": self.created_at_utc,
            "evidence": dict(self.evidence),
            "guardrails": {
                "executionKeyed": True,
                "hiddenSharedStateAllowed": False,
                "durableStorageRequired": False,
                "runtimeOwner": "Hermes-derived FURYOKU",
            },
        }

    def _validate(self) -> None:
        if self.state in {"approved", "resume_approved", "resumed"} and not self.approved_by:
            raise ApprovalResumeError(f"{self.source}: {self.state} requires approvedBy")
        if self.state == "rejected" and not self.reason:
            raise ApprovalResumeError(f"{self.source}: rejected record requires reason")
        if self.state in {"duplicate_blocked", "stale_blocked"} and not self.reason:
            raise ApprovalResumeError(f"{self.source}: {self.state} requires reason")
        if self.state in RESUME_STATES and self.resume is None:
            raise ApprovalResumeError(f"{self.source}: {self.state} requires resume intent")
        if self.attempt_index > 1 and self.resume is None:
            raise ApprovalResumeError(
                f"{self.source}: attemptIndex greater than 1 requires explicit resume intent"
            )
        if self.resume is not None:
            if self.attempt_index <= 1:
                raise ApprovalResumeError(f"{self.source}: resume intent requires attemptIndex greater than 1")
            if self.resume.resume_of != self.workflow_execution_key:
                raise ApprovalResumeError(f"{self.source}: resume.resumeOf must match workflowExecutionKey")
            if self.resume.previous_attempt_index >= self.attempt_index:
                raise ApprovalResumeError(
                    f"{self.source}: resume.previousAttemptIndex must be less than attemptIndex"
                )


@dataclass(frozen=True)
class ApprovalResumeLedger:
    """A bounded set of approval/resume records checked for duplicate ownership."""

    schema_version: int
    records: tuple[ApprovalResumeRecord, ...]
    source: str = "<memory>"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, source: str = "<memory>") -> "ApprovalResumeLedger":
        if not isinstance(payload, Mapping):
            raise ApprovalResumeError(f"{source}: approval/resume ledger must be a JSON object")
        schema_version = _schema_version(payload, source=source)
        raw_records = payload.get("records")
        if not isinstance(raw_records, list) or not raw_records:
            raise ApprovalResumeError(f"{source}: records must be a non-empty array")
        records = tuple(
            ApprovalResumeRecord.from_dict(record, source=f"{source}:records[{index}]")
            for index, record in enumerate(raw_records)
        )
        ledger = cls(schema_version=schema_version, records=records, source=source)
        ledger._validate_unique_record_keys()
        return ledger

    @property
    def record_keys(self) -> tuple[str, ...]:
        return tuple(record.record_key for record in self.records)

    @property
    def workflow_execution_keys(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(record.workflow_execution_key for record in self.records))

    def records_for_handoff(self, handoff_execution_key: str) -> tuple[ApprovalResumeRecord, ...]:
        return tuple(
            record
            for record in self.records
            if record.handoff_execution_key == handoff_execution_key
        )

    def latest_for_handoff(self, handoff_execution_key: str) -> ApprovalResumeRecord | None:
        records = self.records_for_handoff(handoff_execution_key)
        if not records:
            return None
        return max(records, key=lambda record: record.attempt_index)

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "recordKeys": list(self.record_keys),
            "workflowExecutionKeys": list(self.workflow_execution_keys),
            "records": [record.to_dict() for record in self.records],
        }

    def _validate_unique_record_keys(self) -> None:
        seen: dict[str, ApprovalResumeRecord] = {}
        for record in self.records:
            previous = seen.get(record.record_key)
            if previous is not None:
                if previous.owner != record.owner:
                    raise ApprovalResumeError(
                        f"{self.source}: ambiguous ownership for {record.record_key}"
                    )
                raise ApprovalResumeError(f"{self.source}: duplicate approval/resume record for {record.record_key}")
            seen[record.record_key] = record


@dataclass(frozen=True)
class ApprovalResumeConsumptionEvent:
    """Append-only evidence that a handoff consumed one approval/resume record."""

    schema_version: int
    record_key: str
    handoff_execution_key: str
    execution_key: str
    result_status: str
    started_at_utc: str = ""
    finished_at_utc: str = ""
    recoverable_error_code: str = ""
    source: str = "<memory>"

    @property
    def event_key(self) -> str:
        return f"{self.record_key}:consumed:{self.execution_key}"

    @classmethod
    def from_record(
        cls,
        record: ApprovalResumeRecord,
        *,
        execution_key: str | None = None,
        result_status: str = "started",
        started_at_utc: str = "",
        finished_at_utc: str = "",
        recoverable_error_code: str = "",
        source: str = "<memory>",
    ) -> "ApprovalResumeConsumptionEvent":
        event = cls(
            schema_version=1,
            record_key=record.record_key,
            handoff_execution_key=record.handoff_execution_key,
            execution_key=(execution_key or record.handoff_execution_key).strip(),
            result_status=result_status,
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            recoverable_error_code=recoverable_error_code,
            source=source,
        )
        event._validate()
        return event

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        source: str = "<memory>",
    ) -> "ApprovalResumeConsumptionEvent":
        if not isinstance(payload, Mapping):
            raise ApprovalResumeError(f"{source}: approval/resume consumption event must be a JSON object")
        event = cls(
            schema_version=_schema_version(payload, source=source),
            record_key=_required_string(payload, "recordKey", "record_key", source=source),
            handoff_execution_key=_required_string(
                payload,
                "handoffExecutionKey",
                "handoff_execution_key",
                source=source,
            ),
            execution_key=_required_string(payload, "executionKey", "execution_key", source=source),
            result_status=_required_string(payload, "resultStatus", "result_status", source=source),
            started_at_utc=_optional_string(payload, "startedAtUtc", "started_at_utc") or "",
            finished_at_utc=_optional_string(payload, "finishedAtUtc", "finished_at_utc") or "",
            recoverable_error_code=_optional_string(
                payload,
                "recoverableErrorCode",
                "recoverable_error_code",
            )
            or "",
            source=source,
        )
        event._validate()
        return event

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "eventKey": self.event_key,
            "recordKey": self.record_key,
            "handoffExecutionKey": self.handoff_execution_key,
            "executionKey": self.execution_key,
            "resultStatus": self.result_status,
            "startedAtUtc": self.started_at_utc,
            "finishedAtUtc": self.finished_at_utc,
            "recoverableErrorCode": self.recoverable_error_code,
        }

    def _validate(self) -> None:
        if self.schema_version != 1:
            raise ApprovalResumeError(f"{self.source}: unsupported consumption event schemaVersion {self.schema_version!r}")
        for field_name in ("record_key", "handoff_execution_key", "execution_key", "result_status"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ApprovalResumeError(f"{self.source}: {field_name} is required")


@dataclass(frozen=True)
class LocalApprovalResumeLedgerAdapter:
    """Small JSON-backed approval/resume ledger adapter for local durable proof."""

    path: Path

    def __init__(self, path: str | Path):
        object.__setattr__(self, "path", Path(path))

    @property
    def records(self) -> tuple[ApprovalResumeRecord, ...]:
        return tuple(self._read_records_payload()[0])

    @property
    def consumption_events(self) -> tuple[ApprovalResumeConsumptionEvent, ...]:
        return tuple(self._read_records_payload()[1])

    def append_record(self, record: ApprovalResumeRecord) -> ApprovalResumeRecord:
        records, events, payload = self._read_records_payload()
        for existing in records:
            if existing.record_key == record.record_key:
                if existing.owner != record.owner:
                    raise ApprovalResumeError(f"{self.path}: ambiguous ownership for {record.record_key}")
                raise ApprovalResumeError(f"{self.path}: duplicate approval/resume record for {record.record_key}")
        payload["records"] = [existing.to_dict() for existing in records] + [record.to_dict()]
        payload["consumptionEvents"] = [event.to_dict() for event in events]
        self._write_payload(payload)
        return record

    def append_consumption_event(
        self,
        event: ApprovalResumeConsumptionEvent,
    ) -> ApprovalResumeConsumptionEvent:
        records, events, payload = self._read_records_payload()
        records_by_key = {record.record_key: record for record in records}
        record = records_by_key.get(event.record_key)
        if record is None:
            raise ApprovalResumeError(f"{self.path}: consumption event references unknown record {event.record_key}")
        if event.handoff_execution_key != record.handoff_execution_key:
            raise ApprovalResumeError(
                f"{self.path}: consumption event handoffExecutionKey does not match record {event.record_key}"
            )
        for existing in events:
            if existing.event_key == event.event_key:
                raise ApprovalResumeError(f"{self.path}: duplicate consumption event for {event.event_key}")
            if existing.record_key == event.record_key:
                raise ApprovalResumeError(f"{self.path}: approval/resume record {event.record_key} is already consumed")
        payload["records"] = [record.to_dict() for record in records]
        payload["consumptionEvents"] = [existing.to_dict() for existing in events] + [event.to_dict()]
        self._write_payload(payload)
        return event

    def records_for_handoff(self, handoff_execution_key: str) -> tuple[ApprovalResumeRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self.records
                    if record.handoff_execution_key == handoff_execution_key
                ),
                key=_record_order_key,
            )
        )

    def records_for_workflow(self, workflow_execution_key: str) -> tuple[ApprovalResumeRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self.records
                    if record.workflow_execution_key == workflow_execution_key
                ),
                key=_record_order_key,
            )
        )

    def consumption_events_for_record(self, record_key: str) -> tuple[ApprovalResumeConsumptionEvent, ...]:
        return tuple(event for event in self.consumption_events if event.record_key == record_key)

    def is_record_consumed(self, record_key: str) -> bool:
        return bool(self.consumption_events_for_record(record_key))

    def latest_gate_record(
        self,
        handoff_execution_key: str,
        *,
        workflow_execution_key: str | None = None,
    ) -> ApprovalResumeRecord | None:
        records = self.records_for_handoff(handoff_execution_key)
        if workflow_execution_key:
            records = tuple(record for record in records if record.workflow_execution_key == workflow_execution_key)
        if not records:
            return None
        workflow_keys = {record.workflow_execution_key for record in records}
        if len(workflow_keys) > 1:
            raise ApprovalResumeError(
                f"{self.path}: approval/resume ledger has multiple workflow executions for {handoff_execution_key}"
            )
        return max(records, key=_record_order_key)

    def select_gate_record_for_handoff(
        self,
        handoff_execution_key: str,
        *,
        workflow_execution_key: str | None = None,
    ) -> ApprovalResumeRecord | None:
        record = self.latest_gate_record(
            handoff_execution_key,
            workflow_execution_key=workflow_execution_key,
        )
        if record is None:
            return None
        if not record.safe_to_handoff:
            raise ApprovalResumeError(f"{self.path}: approval/resume record state {record.state!r} is not safe to hand off")
        if self.is_record_consumed(record.record_key):
            raise ApprovalResumeError(f"{self.path}: approval/resume record {record.record_key} is already consumed")
        return record

    def to_dict(self) -> dict:
        records, events, _payload = self._read_records_payload()
        return {
            "schemaVersion": 1,
            "records": [record.to_dict() for record in records],
            "consumptionEvents": [event.to_dict() for event in events],
        }

    def _read_records_payload(
        self,
    ) -> tuple[list[ApprovalResumeRecord], list[ApprovalResumeConsumptionEvent], dict]:
        payload = self._read_payload()
        raw_records = payload.get("records", [])
        raw_events = payload.get("consumptionEvents", payload.get("consumption_events", []))
        if not isinstance(raw_records, list):
            raise ApprovalResumeError(f"{self.path}: records must be an array")
        if not isinstance(raw_events, list):
            raise ApprovalResumeError(f"{self.path}: consumptionEvents must be an array")
        records = [
            ApprovalResumeRecord.from_dict(record, source=f"{self.path}:records[{index}]")
            for index, record in enumerate(raw_records)
        ]
        events = [
            ApprovalResumeConsumptionEvent.from_dict(event, source=f"{self.path}:consumptionEvents[{index}]")
            for index, event in enumerate(raw_events)
        ]
        return records, events, payload

    def _read_payload(self) -> dict:
        if not self.path.exists():
            return {"schemaVersion": 1, "records": [], "consumptionEvents": []}
        with self.path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ApprovalResumeError(f"{self.path}: local approval/resume ledger store must be a JSON object")
        _schema_version(payload, source=str(self.path))
        return dict(payload)

    def _write_payload(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        normalized = {
            "schemaVersion": 1,
            "records": list(payload.get("records", [])),
            "consumptionEvents": list(payload.get("consumptionEvents", [])),
        }
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2)
            handle.write("\n")


def load_approval_resume_record(path: str | Path) -> ApprovalResumeRecord:
    record_path = Path(path)
    with record_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return parse_approval_resume_record(payload, source=str(record_path))


def load_approval_resume_ledger(path: str | Path) -> ApprovalResumeLedger:
    ledger_path = Path(path)
    with ledger_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return parse_approval_resume_ledger(payload, source=str(ledger_path))


def parse_approval_resume_record(
    payload: Mapping[str, Any],
    *,
    source: str = "<memory>",
) -> ApprovalResumeRecord:
    return ApprovalResumeRecord.from_dict(payload, source=source)


def parse_approval_resume_ledger(
    payload: Mapping[str, Any],
    *,
    source: str = "<memory>",
) -> ApprovalResumeLedger:
    return ApprovalResumeLedger.from_dict(payload, source=source)


def approval_resume_record_from_workflow_envelope(
    envelope: OperatorReviewedHermesWorkflowEnvelope,
    *,
    owner: str,
) -> ApprovalResumeRecord:
    try:
        return ApprovalResumeRecord.from_workflow_envelope(envelope, owner=owner)
    except WorkflowEnvelopeError as exc:
        raise ApprovalResumeError(str(exc)) from exc


def load_local_approval_resume_ledger_adapter(path: str | Path) -> LocalApprovalResumeLedgerAdapter:
    return LocalApprovalResumeLedgerAdapter(path)


def _record_order_key(record: ApprovalResumeRecord) -> tuple[int, str, str]:
    return (record.attempt_index, record.created_at_utc, record.record_key)


def _schema_version(payload: Mapping[str, Any], *, source: str) -> int:
    raw_version = payload.get("schemaVersion", payload.get("schema_version", 1))
    try:
        schema_version = int(raw_version or 1)
    except (TypeError, ValueError) as exc:
        raise ApprovalResumeError(f"{source}: schemaVersion must be an integer") from exc
    if schema_version != 1:
        raise ApprovalResumeError(f"{source}: unsupported approval/resume schemaVersion {schema_version!r}")
    return schema_version


def _optional_resume_intent(value: Any, *, source: str) -> ResumeIntent | None:
    if value in (None, ""):
        return None
    return ResumeIntent.from_dict(value, source=source)


def _reject_forbidden_record_fields(payload: Mapping[str, Any], *, source: str) -> None:
    forbidden = sorted(key for key in payload if key in FORBIDDEN_RECORD_FIELDS)
    if forbidden:
        names = ", ".join(forbidden)
        raise ApprovalResumeError(
            f"{source}: approval/resume record may not carry hidden shared state or ambiguous ownership fields: {names}"
        )


def _evidence_mapping(value: Any, *, source: str) -> Mapping[str, str]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise ApprovalResumeError(f"{source}: evidence must be a JSON object")
    evidence: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str) or not item.strip():
            raise ApprovalResumeError(f"{source}: evidence.{key} must be a non-empty string")
        evidence[str(key)] = item.strip()
    return evidence


def _required_string(payload: Mapping[str, Any], *keys: str, source: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ApprovalResumeError(f"{source}: {keys[0]} is required")


def _optional_string(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _positive_int(value: Any, *, field_name: str, source: str) -> int:
    if value in (None, ""):
        raise ApprovalResumeError(f"{source}: {field_name} is required")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ApprovalResumeError(f"{source}: {field_name} must be an integer") from exc
    if parsed < 1:
        raise ApprovalResumeError(f"{source}: {field_name} must be at least 1")
    return parsed
