"""Agentic Character Array (ACA) composition surface.

FURYOKU already models a single CHARACTER as an Adaptive Response Array (ARA)
through :mod:`furyoku.character_profiles`: one or more bound role specs with a
primary/secondary distinction and per-role subagent capacity. This module adds
the next layer, the Agentic Character Array (ACA), which composes two or more
Characters into one executable orchestration plan.

The ACA surface intentionally stays passive: it loads member CHARACTER profiles
by path or inline payload and routes each one through the existing CHARACTER
selection pipeline. Array-level semantics (character count, total role count,
total subagent capacity, member responsibilities) are added on top without
altering individual ARA behaviour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .character_profiles import (
    CharacterOrchestrationEnvelope,
    CharacterProfile,
    CharacterProfileError,
    CharacterProfileSelection,
    build_character_orchestration_envelope,
    load_character_profile,
    parse_character_profile,
    select_character_profile_models,
)
from .model_decisions import ReadinessEvidenceInput
from .model_router import ModelEndpoint, RouterError


class CharacterArrayError(ValueError):
    """Raised when an Agentic Character Array composition is malformed."""


@dataclass(frozen=True)
class CharacterArrayMember:
    """One CHARACTER (ARA) bound to an Agentic Character Array slot."""

    profile: CharacterProfile
    alias: str = ""
    responsibility: str = ""
    primary: bool = False

    @property
    def character_id(self) -> str:
        return self.profile.character_id

    @property
    def slot_id(self) -> str:
        return self.alias or self.profile.character_id


@dataclass(frozen=True)
class CharacterArray:
    """A set of CHARACTER members composed into one Agentic Character Array."""

    array_id: str
    array_class: str
    rank: str
    members: tuple[CharacterArrayMember, ...]
    description: str = ""

    @property
    def primary_character_id(self) -> str:
        primary_members = [member.character_id for member in self.members if member.primary]
        return primary_members[0] if primary_members else self.members[0].character_id

    def member(self, slot_id: str) -> CharacterArrayMember:
        for member in self.members:
            if member.slot_id == slot_id:
                return member
        raise CharacterArrayError(f"Unknown CHARACTER ARRAY slot '{slot_id}'")


@dataclass(frozen=True)
class CharacterArrayMemberSelection:
    """Registry-backed ARA selection for one CHARACTER member of an ACA."""

    member: CharacterArrayMember
    selection: CharacterProfileSelection

    @property
    def slot_id(self) -> str:
        return self.member.slot_id

    @property
    def character_id(self) -> str:
        return self.member.character_id


@dataclass(frozen=True)
class CharacterArraySelection:
    """Registry-backed selections for every CHARACTER member of an ACA."""

    array: CharacterArray
    members: Mapping[str, CharacterArrayMemberSelection]

    @property
    def array_id(self) -> str:
        return self.array.array_id

    def member_selection(self, slot_id: str) -> CharacterArrayMemberSelection:
        try:
            return self.members[slot_id]
        except KeyError as exc:
            raise CharacterArrayError(f"Unknown CHARACTER ARRAY slot '{slot_id}'") from exc


@dataclass(frozen=True)
class CharacterArrayMemberEnvelope:
    """One selected CHARACTER inside an Agentic Character Array envelope."""

    member: CharacterArrayMember
    character_envelope: CharacterOrchestrationEnvelope

    @property
    def slot_id(self) -> str:
        return self.member.slot_id

    @property
    def character_id(self) -> str:
        return self.member.character_id

    @property
    def role_count(self) -> int:
        return self.character_envelope.role_count

    @property
    def total_max_subagents(self) -> int:
        return self.character_envelope.total_max_subagents

    def to_dict(self) -> dict:
        return {
            "slotId": self.slot_id,
            "alias": self.member.alias,
            "responsibility": self.member.responsibility,
            "primary": self.member.primary,
            "characterId": self.character_id,
            "character": self.character_envelope.to_dict(),
        }


@dataclass(frozen=True)
class CharacterArrayEnvelope:
    """Serializable assignment plan for an Agentic Character Array."""

    array: CharacterArray
    members: tuple[CharacterArrayMemberEnvelope, ...]

    @property
    def array_id(self) -> str:
        return self.array.array_id

    @property
    def primary_character_id(self) -> str:
        return self.array.primary_character_id

    @property
    def character_count(self) -> int:
        return len(self.members)

    @property
    def total_role_count(self) -> int:
        return sum(member.role_count for member in self.members)

    @property
    def total_max_subagents(self) -> int:
        return sum(member.total_max_subagents for member in self.members)

    def member_envelope(self, slot_id: str) -> CharacterArrayMemberEnvelope:
        for member_envelope in self.members:
            if member_envelope.slot_id == slot_id:
                return member_envelope
        raise CharacterArrayError(f"Unknown CHARACTER ARRAY slot '{slot_id}'")

    def to_dict(self) -> dict:
        return {
            "arrayId": self.array.array_id,
            "class": self.array.array_class,
            "rank": self.array.rank,
            "description": self.array.description,
            "primaryCharacterId": self.primary_character_id,
            "characterCount": self.character_count,
            "totalRoleCount": self.total_role_count,
            "totalMaxSubagents": self.total_max_subagents,
            "members": [member.to_dict() for member in self.members],
        }


def load_character_array(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> CharacterArray:
    """Load an Agentic Character Array from a JSON file."""

    array_path = Path(path)
    with array_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return parse_character_array(
        payload,
        source=str(array_path),
        base_dir=Path(base_dir) if base_dir is not None else array_path.parent,
    )


def parse_character_array(
    payload: Mapping[str, Any],
    *,
    source: str = "<memory>",
    base_dir: str | Path | None = None,
) -> CharacterArray:
    """Parse an Agentic Character Array JSON payload."""

    if not isinstance(payload, Mapping):
        raise CharacterArrayError(f"{source}: CHARACTER ARRAY must be a JSON object")

    schema_version = payload.get("schemaVersion", payload.get("schema_version", 1))
    if schema_version != 1:
        raise CharacterArrayError(
            f"{source}: unsupported CHARACTER ARRAY schemaVersion {schema_version!r}"
        )

    array_id = str(payload.get("arrayId", payload.get("array_id", "")) or "").strip()
    if not array_id:
        raise CharacterArrayError(f"{source}: arrayId is required")

    members_payload = payload.get("members")
    if not isinstance(members_payload, list) or not members_payload:
        raise CharacterArrayError(f"{source}: members must be a non-empty array")

    resolved_base_dir = Path(base_dir) if base_dir is not None else None
    members = tuple(
        _parse_member(raw, source=source, index=index, base_dir=resolved_base_dir)
        for index, raw in enumerate(members_payload)
    )
    _validate_members(members, source=source)

    return CharacterArray(
        array_id=array_id,
        array_class=str(
            payload.get(
                "class",
                payload.get("arrayClass", payload.get("array_class", "")),
            )
            or ""
        ),
        rank=str(payload.get("rank", "") or ""),
        description=str(payload.get("description", "") or ""),
        members=members,
    )


def select_character_array_models(
    models: Iterable[ModelEndpoint],
    array: CharacterArray,
    *,
    allow_reuse: bool = True,
    readiness: ReadinessEvidenceInput | None = None,
) -> CharacterArraySelection:
    """Select concrete model endpoints for every CHARACTER member in an ACA."""

    if not isinstance(array, CharacterArray):
        raise RouterError("CHARACTER ARRAY selection requires a parsed CharacterArray")

    model_list = list(models)
    member_selections: dict[str, CharacterArrayMemberSelection] = {}
    for member in array.members:
        profile_selection = select_character_profile_models(
            model_list,
            member.profile,
            allow_reuse=allow_reuse,
            readiness=readiness,
        )
        member_selections[member.slot_id] = CharacterArrayMemberSelection(
            member=member,
            selection=profile_selection,
        )
    return CharacterArraySelection(array=array, members=member_selections)


def build_character_array_envelope(
    selection: CharacterArraySelection,
) -> CharacterArrayEnvelope:
    """Compose per-member ARA envelopes into one ACA envelope."""

    member_envelopes = tuple(
        CharacterArrayMemberEnvelope(
            member=selection.member_selection(member.slot_id).member,
            character_envelope=build_character_orchestration_envelope(
                selection.member_selection(member.slot_id).selection
            ),
        )
        for member in selection.array.members
    )
    return CharacterArrayEnvelope(array=selection.array, members=member_envelopes)


def select_character_array_envelope(
    models: Iterable[ModelEndpoint],
    array: CharacterArray,
    *,
    allow_reuse: bool = True,
    readiness: ReadinessEvidenceInput | None = None,
) -> CharacterArrayEnvelope:
    """Select CHARACTER ARRAY members and return an executable envelope."""

    selection = select_character_array_models(
        models,
        array,
        allow_reuse=allow_reuse,
        readiness=readiness,
    )
    return build_character_array_envelope(selection)


def _parse_member(
    raw: Mapping[str, Any],
    *,
    source: str,
    index: int,
    base_dir: Path | None,
) -> CharacterArrayMember:
    if not isinstance(raw, Mapping):
        raise CharacterArrayError(f"{source}: members[{index}] must be a JSON object")

    profile = _resolve_member_profile(raw, source=source, index=index, base_dir=base_dir)
    alias = str(raw.get("alias", "") or "").strip()
    responsibility = str(raw.get("responsibility", "") or "").strip()
    primary = bool(raw.get("primary", False))
    return CharacterArrayMember(
        profile=profile,
        alias=alias,
        responsibility=responsibility,
        primary=primary,
    )


def _resolve_member_profile(
    raw: Mapping[str, Any],
    *,
    source: str,
    index: int,
    base_dir: Path | None,
) -> CharacterProfile:
    profile_payload = raw.get("profile")
    profile_path_value = raw.get("profilePath", raw.get("profile_path"))
    inline_payload = raw.get("character", raw.get("inline"))

    provided = [name for name, value in {
        "profile": profile_payload,
        "profilePath": profile_path_value,
        "character": inline_payload,
    }.items() if value is not None]
    if len(provided) != 1:
        raise CharacterArrayError(
            f"{source}: members[{index}] requires exactly one of "
            f"'profile', 'profilePath', or 'character' (got {provided or ['none']})"
        )

    if inline_payload is not None:
        if not isinstance(inline_payload, Mapping):
            raise CharacterArrayError(
                f"{source}: members[{index}].character must be a JSON object"
            )
        try:
            return parse_character_profile(
                inline_payload,
                source=f"{source}:members[{index}].character",
            )
        except CharacterProfileError as exc:
            raise CharacterArrayError(str(exc)) from exc

    if profile_payload is not None:
        if not isinstance(profile_payload, Mapping):
            raise CharacterArrayError(
                f"{source}: members[{index}].profile must be a JSON object"
            )
        try:
            return parse_character_profile(
                profile_payload,
                source=f"{source}:members[{index}].profile",
            )
        except CharacterProfileError as exc:
            raise CharacterArrayError(str(exc)) from exc

    profile_path = Path(str(profile_path_value or "").strip())
    if not str(profile_path):
        raise CharacterArrayError(
            f"{source}: members[{index}].profilePath must be a non-empty string"
        )
    if not profile_path.is_absolute() and base_dir is not None:
        profile_path = base_dir / profile_path
    try:
        return load_character_profile(profile_path)
    except CharacterProfileError as exc:
        raise CharacterArrayError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise CharacterArrayError(
            f"{source}: members[{index}].profilePath '{profile_path}' was not found"
        ) from exc


def _validate_members(
    members: Sequence[CharacterArrayMember],
    *,
    source: str,
) -> None:
    seen_slots: set[str] = set()
    seen_characters: set[str] = set()
    primary_count = 0
    for member in members:
        if member.slot_id in seen_slots:
            raise CharacterArrayError(
                f"{source}: duplicate CHARACTER ARRAY slotId '{member.slot_id}'"
            )
        if member.character_id in seen_characters:
            raise CharacterArrayError(
                f"{source}: duplicate CHARACTER ARRAY characterId '{member.character_id}'"
            )
        seen_slots.add(member.slot_id)
        seen_characters.add(member.character_id)
        if member.primary:
            primary_count += 1
    if primary_count > 1:
        raise CharacterArrayError(
            f"{source}: only one CHARACTER ARRAY member can be primary"
        )
