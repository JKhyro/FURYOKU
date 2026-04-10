import unittest
from pathlib import Path

from furyoku import RegistryError, load_model_registry, parse_model_registry, select_character_panel, select_model
from furyoku.model_router import TaskProfile


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REGISTRY = ROOT / "examples" / "model_registry.example.json"


class ModelRegistryTests(unittest.TestCase):
    def test_load_example_registry_for_character_panel(self):
        models = load_model_registry(EXAMPLE_REGISTRY)

        panel = select_character_panel(models, allow_reuse=False)

        self.assertEqual(panel.face.model.model_id, "cli-codex-high")
        self.assertEqual(panel.memory.model.model_id, "api-long-context-memory")
        self.assertEqual(panel.reasoning.model.model_id, "local-gemma3-heretic-q4")

    def test_registry_drives_local_only_selection(self):
        models = load_model_registry(EXAMPLE_REGISTRY)
        task = TaskProfile(
            task_id="private-local-response",
            required_capabilities={"conversation": 0.8, "instruction_following": 0.8},
            privacy_requirement="local_only",
        )

        selected = select_model(models, task)

        self.assertEqual(selected.model.provider, "local")
        self.assertEqual(selected.model.invocation[0], "ollama")

    def test_duplicate_model_ids_are_rejected(self):
        payload = {
            "schemaVersion": 1,
            "models": [
                {
                    "modelId": "duplicate",
                    "provider": "local",
                    "contextWindowTokens": 1000,
                    "averageLatencyMs": 10,
                    "capabilities": {"conversation": 1.0},
                },
                {
                    "modelId": "duplicate",
                    "provider": "api",
                    "contextWindowTokens": 1000,
                    "averageLatencyMs": 10,
                    "capabilities": {"conversation": 1.0},
                },
            ],
        }

        with self.assertRaises(RegistryError) as error:
            parse_model_registry(payload)

        self.assertIn("duplicate model ids", str(error.exception))

    def test_missing_capabilities_are_rejected(self):
        payload = {
            "schemaVersion": 1,
            "models": [
                {
                    "modelId": "broken",
                    "provider": "local",
                    "contextWindowTokens": 1000,
                    "averageLatencyMs": 10,
                },
            ],
        }

        with self.assertRaises(RegistryError) as error:
            parse_model_registry(payload)

        self.assertIn("capabilities", str(error.exception))


if __name__ == "__main__":
    unittest.main()
