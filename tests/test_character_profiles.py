import unittest
from pathlib import Path

from furyoku import CharacterProfileError, load_character_profile, parse_character_profile


ROOT = Path(__file__).resolve().parents[1]
TERTIARY_PROFILE = ROOT / "examples" / "character_profile.tertiary-symbiote.json"
KIRA_PROFILE = ROOT / "examples" / "character_profile.kira-array.json"


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
