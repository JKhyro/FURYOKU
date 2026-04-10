import unittest

from furyoku import (
    ModelEndpoint,
    RouterError,
    TaskProfile,
    rank_models,
    select_character_panel,
    select_model,
)


def sample_models():
    return [
        ModelEndpoint(
            model_id="local-gemma3-heretic-q4",
            provider="local",
            privacy_level="local",
            context_window_tokens=8192,
            average_latency_ms=1800,
            capabilities={
                "conversation": 0.82,
                "instruction_following": 0.84,
                "safety": 0.72,
                "speed": 0.95,
                "retrieval": 0.62,
                "summarization": 0.7,
                "reasoning": 0.91,
                "coding": 0.82,
            },
            supports_json=True,
        ),
        ModelEndpoint(
            model_id="cli-codex-high",
            provider="cli",
            privacy_level="remote",
            context_window_tokens=128000,
            average_latency_ms=7000,
            input_cost_per_1k=0.02,
            output_cost_per_1k=0.08,
            capabilities={
                "conversation": 0.88,
                "instruction_following": 0.94,
                "safety": 0.86,
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
            model_id="api-long-context-memory",
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


class ModelRouterTests(unittest.TestCase):
    def test_select_model_prefers_local_when_task_requires_local(self):
        task = TaskProfile(
            task_id="private-chat",
            required_capabilities={
                "conversation": 0.75,
                "instruction_following": 0.7,
            },
            privacy_requirement="local_only",
        )

        selected = select_model(sample_models(), task)

        self.assertEqual(selected.model.model_id, "local-gemma3-heretic-q4")
        self.assertTrue(selected.eligible)

    def test_select_model_uses_cli_for_hard_coding_reasoning(self):
        task = TaskProfile(
            task_id="hard-coding",
            required_capabilities={
                "reasoning": 0.9,
                "coding": 0.9,
                "instruction_following": 0.85,
            },
            require_tools=True,
        )

        selected = select_model(sample_models(), task)

        self.assertEqual(selected.model.model_id, "cli-codex-high")
        self.assertTrue(selected.eligible)

    def test_rank_models_surfaces_blockers_for_ineligible_models(self):
        task = TaskProfile(
            task_id="json-memory",
            required_capabilities={"retrieval": 0.9},
            min_context_tokens=64000,
            require_json=True,
        )

        ranked = rank_models(sample_models(), task)
        local_score = next(score for score in ranked if score.model.model_id == "local-gemma3-heretic-q4")

        self.assertFalse(local_score.eligible)
        self.assertTrue(any("context window" in blocker for blocker in local_score.blockers))

    def test_character_panel_can_select_three_distinct_role_models(self):
        panel = select_character_panel(sample_models(), allow_reuse=False)

        self.assertEqual(panel.face.model.model_id, "cli-codex-high")
        self.assertEqual(panel.memory.model.model_id, "api-long-context-memory")
        self.assertEqual(panel.reasoning.model.model_id, "local-gemma3-heretic-q4")
        self.assertEqual(len({score.model.model_id for score in panel.as_dict().values()}), 3)

    def test_no_eligible_model_raises_with_blocker_summary(self):
        task = TaskProfile(
            task_id="impossible-local-coder",
            required_capabilities={"coding": 0.99},
            privacy_requirement="local_only",
        )

        with self.assertRaises(RouterError) as error:
            select_model(sample_models(), task)

        self.assertIn("No eligible model", str(error.exception))
        self.assertIn("coding capability", str(error.exception))


if __name__ == "__main__":
    unittest.main()
