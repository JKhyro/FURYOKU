import json
import tempfile
import unittest
from pathlib import Path

from furyoku import (
    CharacterArray,
    CharacterArrayEnvelope,
    CharacterArrayError,
    CharacterArrayMember,
    ModelEndpoint,
    ProviderHealthCheckResult,
    build_character_array_envelope,
    load_character_array,
    parse_character_array,
    select_character_array_envelope,
    select_character_array_models,
)


ROOT = Path(__file__).resolve().parents[1]
DUAL_ARRAY = ROOT / "examples" / "character_array.dual-symbiote.json"
KIRA_PROFILE = ROOT / "examples" / "character_profile.kira-array.json"
TERTIARY_PROFILE = ROOT / "examples" / "character_profile.tertiary-symbiote.json"


def sample_models():
    return [
        ModelEndpoint(
            model_id="local-gemma",
            provider="local",
            privacy_level="local",
            context_window_tokens=8192,
            average_latency_ms=1800,
            capabilities={
                "conversation": 0.84,
                "instruction_following": 0.84,
                "safety": 0.74,
                "speed": 0.95,
                "retrieval": 0.64,
                "summarization": 0.72,
                "reasoning": 0.91,
                "coding": 0.82,
            },
            supports_json=True,
        ),
        ModelEndpoint(
            model_id="cli-codex",
            provider="cli",
            privacy_level="remote",
            context_window_tokens=128000,
            average_latency_ms=7000,
            input_cost_per_1k=0.02,
            output_cost_per_1k=0.08,
            capabilities={
                "conversation": 0.92,
                "instruction_following": 0.94,
                "safety": 0.91,
                "speed": 0.72,
                "retrieval": 0.82,
                "summarization": 0.9,
                "reasoning": 0.96,
                "coding": 0.95,
            },
            supports_json=True,
            supports_tools=True,
        ),
        ModelEndpoint(
            model_id="api-memory",
            provider="api",
            privacy_level="remote",
            context_window_tokens=200000,
            average_latency_ms=5000,
            input_cost_per_1k=0.004,
            output_cost_per_1k=0.012,
            capabilities={
                "conversation": 0.84,
                "instruction_following": 0.86,
                "safety": 0.83,
                "speed": 0.78,
                "retrieval": 0.95,
                "summarization": 0.93,
                "reasoning": 0.84,
                "coding": 0.72,
            },
            supports_json=True,
        ),
    ]


class CharacterArrayLoadingTests(unittest.TestCase):
    def test_load_dual_symbiote_example(self):
        array = load_character_array(DUAL_ARRAY)

        self.assertIsInstance(array, CharacterArray)
        self.assertEqual(array.array_id, "dual-symbiote")
        self.assertEqual(array.array_class, "Symbiote")
        self.assertEqual(array.rank, "Prototype")
        self.assertEqual(len(array.members), 2)

        kira_member, tertiary_member = array.members
        self.assertIsInstance(kira_member, CharacterArrayMember)
        self.assertTrue(kira_member.primary)
        self.assertEqual(kira_member.alias, "kira-lead")
        self.assertEqual(kira_member.character_id, "kira")
        self.assertFalse(tertiary_member.primary)
        self.assertEqual(tertiary_member.slot_id, "tertiary-support")
        self.assertEqual(tertiary_member.character_id, "tertiary-symbiote")

    def test_parse_character_array_accepts_inline_character_payload(self):
        payload = {
            "schemaVersion": 1,
            "arrayId": "inline-array",
            "class": "Symbiote",
            "rank": "Prototype",
            "members": [
                {
                    "alias": "lead",
                    "primary": True,
                    "character": {
                        "schemaVersion": 1,
                        "characterId": "inline-lead",
                        "roles": [
                            {
                                "roleId": "primary",
                                "primary": True,
                                "task": {
                                    "taskId": "inline-lead.primary",
                                    "requiredCapabilities": {"conversation": 0.8},
                                },
                            }
                        ],
                    },
                },
                {
                    "alias": "support",
                    "character": {
                        "schemaVersion": 1,
                        "characterId": "inline-support",
                        "roles": [
                            {
                                "roleId": "primary",
                                "primary": True,
                                "task": {
                                    "taskId": "inline-support.primary",
                                    "requiredCapabilities": {"conversation": 0.7},
                                },
                            }
                        ],
                    },
                },
            ],
        }

        array = parse_character_array(payload)

        self.assertEqual(array.array_id, "inline-array")
        self.assertEqual(array.members[0].character_id, "inline-lead")
        self.assertEqual(array.members[1].character_id, "inline-support")
        self.assertEqual(array.primary_character_id, "inline-lead")

    def test_load_character_array_accepts_utf8_bom_file(self):
        payload = {
            "schemaVersion": 1,
            "arrayId": "bom-array",
            "members": [
                {
                    "alias": "primary",
                    "primary": True,
                    "profilePath": str(KIRA_PROFILE),
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "array.json"
            path.write_text(json.dumps(payload), encoding="utf-8-sig")
            array = load_character_array(path)

        self.assertEqual(array.array_id, "bom-array")
        self.assertEqual(array.members[0].character_id, "kira")


class CharacterArrayValidationTests(unittest.TestCase):
    def _inline_payload(self, character_id: str, capability: float = 0.8):
        return {
            "schemaVersion": 1,
            "characterId": character_id,
            "roles": [
                {
                    "roleId": "primary",
                    "primary": True,
                    "task": {
                        "taskId": f"{character_id}.primary",
                        "requiredCapabilities": {"conversation": capability},
                    },
                }
            ],
        }

    def test_duplicate_character_ids_are_rejected(self):
        payload = {
            "schemaVersion": 1,
            "arrayId": "broken",
            "members": [
                {"alias": "a", "primary": True, "character": self._inline_payload("dup")},
                {"alias": "b", "character": self._inline_payload("dup")},
            ],
        }

        with self.assertRaises(CharacterArrayError) as error:
            parse_character_array(payload)

        self.assertIn("duplicate", str(error.exception))

    def test_duplicate_slot_aliases_are_rejected(self):
        payload = {
            "schemaVersion": 1,
            "arrayId": "broken",
            "members": [
                {"alias": "shared", "primary": True, "character": self._inline_payload("a")},
                {"alias": "shared", "character": self._inline_payload("b")},
            ],
        }

        with self.assertRaises(CharacterArrayError) as error:
            parse_character_array(payload)

        self.assertIn("slotId", str(error.exception))

    def test_multiple_primary_members_are_rejected(self):
        payload = {
            "schemaVersion": 1,
            "arrayId": "broken",
            "members": [
                {"alias": "a", "primary": True, "character": self._inline_payload("a")},
                {"alias": "b", "primary": True, "character": self._inline_payload("b")},
            ],
        }

        with self.assertRaises(CharacterArrayError) as error:
            parse_character_array(payload)

        self.assertIn("only one", str(error.exception))

    def test_member_requires_exactly_one_of_profile_profile_path_character(self):
        payload = {
            "schemaVersion": 1,
            "arrayId": "broken",
            "members": [
                {"alias": "none"},
            ],
        }

        with self.assertRaises(CharacterArrayError) as error:
            parse_character_array(payload)

        self.assertIn("exactly one", str(error.exception))


class CharacterArraySelectionTests(unittest.TestCase):
    def test_select_character_array_models_populates_each_member(self):
        array = load_character_array(DUAL_ARRAY)

        selection = select_character_array_models(sample_models(), array)

        self.assertEqual(selection.array_id, "dual-symbiote")
        self.assertEqual(set(selection.members), {"kira-lead", "tertiary-support"})

        kira_selection = selection.member_selection("kira-lead").selection
        tertiary_selection = selection.member_selection("tertiary-support").selection
        self.assertEqual(kira_selection.character_id, "kira")
        self.assertEqual(tertiary_selection.character_id, "tertiary-symbiote")
        self.assertEqual(kira_selection.roles["memory"].model.model_id, "api-memory")

    def test_select_character_array_envelope_sums_totals_across_members(self):
        array = load_character_array(DUAL_ARRAY)

        envelope = select_character_array_envelope(sample_models(), array)

        self.assertIsInstance(envelope, CharacterArrayEnvelope)
        self.assertEqual(envelope.character_count, 2)
        self.assertEqual(envelope.total_role_count, 9)
        self.assertEqual(envelope.total_max_subagents, 96)
        self.assertEqual(envelope.primary_character_id, "kira")

        payload = envelope.to_dict()
        self.assertEqual(payload["arrayId"], "dual-symbiote")
        self.assertEqual(payload["characterCount"], 2)
        self.assertEqual(payload["totalRoleCount"], 9)
        self.assertEqual(payload["totalMaxSubagents"], 96)
        self.assertEqual(payload["primaryCharacterId"], "kira")
        self.assertEqual(len(payload["members"]), 2)
        self.assertEqual(payload["members"][0]["slotId"], "kira-lead")
        self.assertTrue(payload["members"][0]["primary"])
        self.assertEqual(payload["members"][0]["character"]["characterId"], "kira")
        self.assertEqual(payload["members"][1]["slotId"], "tertiary-support")
        self.assertEqual(
            payload["members"][1]["character"]["characterId"],
            "tertiary-symbiote",
        )

    def test_build_character_array_envelope_preserves_individual_ara_envelopes(self):
        array = load_character_array(DUAL_ARRAY)
        selection = select_character_array_models(sample_models(), array)

        envelope = build_character_array_envelope(selection)

        kira_member = envelope.member_envelope("kira-lead")
        self.assertEqual(kira_member.role_count, 8)
        self.assertEqual(kira_member.total_max_subagents, 96)
        tertiary_member = envelope.member_envelope("tertiary-support")
        self.assertEqual(tertiary_member.role_count, 1)
        self.assertEqual(tertiary_member.total_max_subagents, 0)

    def test_readiness_evidence_flows_through_to_member_selection(self):
        array = parse_character_array(
            {
                "schemaVersion": 1,
                "arrayId": "readiness-array",
                "members": [
                    {
                        "alias": "solo",
                        "primary": True,
                        "character": {
                            "schemaVersion": 1,
                            "characterId": "readiness-character",
                            "roles": [
                                {
                                    "roleId": "primary",
                                    "primary": True,
                                    "task": {
                                        "taskId": "readiness-character.primary",
                                        "requiredCapabilities": {"conversation": 0.8},
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        )

        selection = select_character_array_models(
            sample_models()[:2],
            array,
            readiness=[
                ProviderHealthCheckResult(
                    model_id="cli-codex",
                    provider="cli",
                    status="missing-command",
                    ready=False,
                    reason="command 'codex' was not found",
                    command="codex",
                ),
                ProviderHealthCheckResult(
                    model_id="local-gemma",
                    provider="local",
                    status="ready",
                    ready=True,
                    reason="command is available",
                ),
            ],
        )

        solo = selection.member_selection("solo").selection
        self.assertEqual(solo.roles["primary"].model.model_id, "local-gemma")


if __name__ == "__main__":
    unittest.main()
