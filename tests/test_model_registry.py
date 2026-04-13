import json
import tempfile
import unittest
from pathlib import Path

from furyoku import (
    CharacterRoleSpec,
    RegistryError,
    load_model_registry,
    parse_model_registry,
    select_character_composition,
    select_character_panel,
    select_model,
)
from furyoku.model_router import TaskProfile


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REGISTRY = ROOT / "examples" / "model_registry.example.json"
CANDIDATE_REGISTRY = ROOT / "benchmarks" / "openclaw-local-llm" / "candidates.json"
APPROVED_LOCAL_MODELS = {
    "gemma4-e4b-ultra-heretic:q8_0",
    "gemma4-e4b-hauhau-aggressive:q8kp",
    "gemma4-e2b-hauhau-aggressive:q8kp",
    "gemma3-12b-ultra-heretic:q8_0",
    "gemma4-26b-a4b-heretic:q4_k_m",
    "gemma4-26b-a4b-heretic:q8_0",
    "gemma4-26b-a4b-ultra-heretic:q4_k_m",
    "gemma4-26b-a4b-ultra-heretic:q8_0",
    "gemma4-31b-heretic:q4_k_m",
}


class ModelRegistryTests(unittest.TestCase):
    def test_load_example_registry_for_character_panel(self):
        models = load_model_registry(EXAMPLE_REGISTRY)

        panel = select_character_panel(models, allow_reuse=False)

        self.assertEqual(panel.face.model.model_id, "cli-codex-high")
        self.assertEqual(panel.memory.model.model_id, "api-long-context-memory")
        self.assertEqual(panel.reasoning.model.model_id, "local-gemma4-e4b-ultra-q8")

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

    def test_registry_drives_single_role_character_composition(self):
        models = load_model_registry(EXAMPLE_REGISTRY)
        task = TaskProfile(
            task_id="symbiote.tertiary.primary",
            required_capabilities={"conversation": 0.8, "instruction_following": 0.8},
            privacy_requirement="local_only",
        )

        composition = select_character_composition(
            models,
            [CharacterRoleSpec("primary", task, primary=True)],
        )

        self.assertEqual(composition.primary_role, "primary")
        self.assertEqual(composition.roles["primary"].model.model_id, "local-gemma4-e4b-ultra-q8")

    def test_example_registry_uses_only_approved_local_model_invocations(self):
        payload = json.loads(EXAMPLE_REGISTRY.read_text(encoding="utf-8"))
        local_invocations = {
            model["invocation"][-1]
            for model in payload["models"]
            if model.get("provider") == "local"
        }

        self.assertTrue(local_invocations)
        self.assertLessEqual(local_invocations, APPROVED_LOCAL_MODELS)

    def test_active_candidate_registry_uses_only_approved_local_models(self):
        payload = json.loads(CANDIDATE_REGISTRY.read_text(encoding="utf-8"))
        candidate_models = {entry["model"] for entry in payload}

        self.assertEqual(candidate_models, APPROVED_LOCAL_MODELS)

    def test_registry_parses_api_transport_metadata(self):
        payload = {
            "schemaVersion": 1,
            "models": [
                {
                    "modelId": "api-configured",
                    "provider": "api",
                    "contextWindowTokens": 128000,
                    "averageLatencyMs": 20,
                    "apiUrl": "https://api.example.invalid/v1/chat/completions",
                    "apiKeyEnv": "FURYOKU_API_KEY",
                    "apiModel": "remote-model",
                    "capabilities": {"conversation": 1.0},
                    "metadata": {"apiFormat": "openai-chat", "owner": "test"},
                }
            ],
        }

        models = parse_model_registry(payload)

        self.assertEqual(models[0].metadata["apiUrl"], "https://api.example.invalid/v1/chat/completions")
        self.assertEqual(models[0].metadata["apiKeyEnv"], "FURYOKU_API_KEY")
        self.assertEqual(models[0].metadata["apiModel"], "remote-model")
        self.assertEqual(models[0].metadata["apiFormat"], "openai-chat")
        self.assertEqual(models[0].metadata["owner"], "test")

    def test_load_registry_accepts_utf8_bom_file(self):
        payload = {
            "schemaVersion": 1,
            "models": [
                {
                    "modelId": "local-ready",
                    "provider": "local",
                    "contextWindowTokens": 4096,
                    "averageLatencyMs": 20,
                    "capabilities": {"conversation": 0.9},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "registry.json"
            path.write_text(json.dumps(payload), encoding="utf-8-sig")
            models = load_model_registry(path)

        self.assertEqual(models[0].model_id, "local-ready")

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
