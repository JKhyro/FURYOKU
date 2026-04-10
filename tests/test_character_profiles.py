import unittest
from pathlib import Path

from furyoku import (
    CharacterProfileError,
    ModelEndpoint,
    load_character_profile,
    parse_character_profile,
    select_character_profile_models,
)


ROOT = Path(__file__).resolve().parents[1]
TERTIARY_PROFILE = ROOT / "examples" / "character_profile.tertiary-symbiote.json"
KIRA_PROFILE = ROOT / "examples" / "character_profile.kira-array.json"


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


class CharacterProfileTests(unittest.TestCase):
    def test_load_tertiary_symbiote_single_role_profile(self):
        profile = load_character_profile(TERTIARY_PROFILE)

        self.assertEqual(profile.character_id, "tertiary-symbiote")
        self.assertEqual(profile.character_class, "Symbiote")
        self.assertEqual(profile.rank, "Tertiary")
        self.assertEqual(profile.primary_role_id, "primary")
        self.assertEqual(len(profile.role_specs), 1)
        self.assertEqual(profile.role_specs[0].max_subagents, 0)

    def test_load_kira_profile_with_one_primary_and_seven_secondary_roles(self):
        profile = load_character_profile(KIRA_PROFILE)

        self.assertEqual(profile.character_id, "kira")
        self.assertEqual(profile.primary_role_id, "primary")
        self.assertEqual(len(profile.role_specs), 8)
        self.assertTrue(profile.role_specs[0].primary)
        self.assertTrue(all(role.max_subagents == 12 for role in profile.role_specs))
        self.assertEqual([role.role_id for role in profile.role_specs][1], "memory")

    def test_select_character_profile_models_handles_single_role_profile(self):
        profile = load_character_profile(TERTIARY_PROFILE)

        selection = select_character_profile_models(sample_models(), profile)

        self.assertEqual(selection.character_id, "tertiary-symbiote")
        self.assertEqual(selection.primary_role, "primary")
        self.assertEqual(list(selection.roles), ["primary"])
        self.assertEqual(selection.roles["primary"].model.model_id, "local-gemma")
        self.assertEqual(selection.max_subagents_for("primary"), 0)

    def test_select_character_profile_models_preserves_kira_role_metadata(self):
        profile = load_character_profile(KIRA_PROFILE)

        selection = select_character_profile_models(sample_models(), profile)

        self.assertEqual(selection.character_id, "kira")
        self.assertEqual(selection.primary_role, "primary")
        self.assertEqual(len(selection.roles), 8)
        self.assertEqual(selection.roles["memory"].model.model_id, "api-memory")
        self.assertEqual(selection.roles["coding"].model.model_id, "cli-codex")
        self.assertEqual(selection.max_subagents_for("reflection"), 12)

    def test_duplicate_roles_are_rejected(self):
        payload = {
            "schemaVersion": 1,
            "characterId": "broken",
            "roles": [
                {
                    "roleId": "primary",
                    "primary": True,
                    "task": {"taskId": "a", "requiredCapabilities": {"conversation": 0.5}},
                },
                {
                    "roleId": "primary",
                    "task": {"taskId": "b", "requiredCapabilities": {"conversation": 0.5}},
                },
            ],
        }

        with self.assertRaises(CharacterProfileError) as error:
            parse_character_profile(payload)

        self.assertIn("duplicate roleId", str(error.exception))

    def test_multiple_primary_roles_are_rejected(self):
        payload = {
            "schemaVersion": 1,
            "characterId": "broken",
            "roles": [
                {
                    "roleId": "a",
                    "primary": True,
                    "task": {"taskId": "a", "requiredCapabilities": {"conversation": 0.5}},
                },
                {
                    "roleId": "b",
                    "primary": True,
                    "task": {"taskId": "b", "requiredCapabilities": {"conversation": 0.5}},
                },
            ],
        }

        with self.assertRaises(CharacterProfileError) as error:
            parse_character_profile(payload)

        self.assertIn("only one role", str(error.exception))


if __name__ == "__main__":
    unittest.main()
