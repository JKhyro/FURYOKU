import unittest

from furyoku import (
    CharacterRoleSpec,
    ModelEndpoint,
    RouterError,
    RoutingScorePolicy,
    TaskProfile,
    build_routing_score_policy_metadata,
    parse_routing_score_policy,
    rank_models,
    select_character_composition,
    select_character_panel,
    select_model,
)


def sample_models():
    return [
        ModelEndpoint(
            model_id="local-gemma4-e4b-ultra-q8",
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

        self.assertEqual(selected.model.model_id, "local-gemma4-e4b-ultra-q8")
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

    def test_default_routing_score_policy_preserves_selection(self):
        task = TaskProfile(
            task_id="hard-coding",
            required_capabilities={
                "reasoning": 0.9,
                "coding": 0.9,
                "instruction_following": 0.85,
            },
            require_tools=True,
        )

        default_selected = select_model(sample_models(), task)
        policy_selected = select_model(sample_models(), task, policy=RoutingScorePolicy())

        self.assertEqual(policy_selected.model.model_id, default_selected.model.model_id)
        self.assertEqual(policy_selected.score, default_selected.score)
        self.assertEqual(policy_selected.reasons, default_selected.reasons)

    def test_custom_speed_heavy_policy_can_change_eligible_ranking(self):
        models = [
            ModelEndpoint(
                model_id="fast-local",
                provider="local",
                privacy_level="local",
                context_window_tokens=4096,
                average_latency_ms=100,
                capabilities={"conversation": 0.82},
            ),
            ModelEndpoint(
                model_id="slow-remote",
                provider="api",
                privacy_level="remote",
                context_window_tokens=128000,
                average_latency_ms=5000,
                capabilities={"conversation": 0.95},
            ),
        ]
        task = TaskProfile(task_id="chat", required_capabilities={"conversation": 0.8})

        default_selected = select_model(models, task)
        speed_selected = select_model(
            models,
            task,
            policy=RoutingScorePolicy(capability_weight=40.0, speed_bonus_weight=80.0),
        )

        self.assertEqual(default_selected.model.model_id, "slow-remote")
        self.assertEqual(speed_selected.model.model_id, "fast-local")
        self.assertTrue(any("speed bonus" in reason for reason in speed_selected.reasons))

    def test_custom_cost_policy_can_demote_expensive_eligible_model(self):
        models = [
            ModelEndpoint(
                model_id="cheap-local",
                provider="local",
                privacy_level="local",
                context_window_tokens=4096,
                average_latency_ms=1200,
                input_cost_per_1k=0.0,
                output_cost_per_1k=0.0,
                capabilities={"summarization": 0.82},
            ),
            ModelEndpoint(
                model_id="expensive-api",
                provider="api",
                privacy_level="remote",
                context_window_tokens=128000,
                average_latency_ms=1200,
                input_cost_per_1k=0.08,
                output_cost_per_1k=0.12,
                capabilities={"summarization": 0.95},
            ),
        ]
        task = TaskProfile(task_id="summary", required_capabilities={"summarization": 0.8})

        default_selected = select_model(models, task)
        cheap_selected = select_model(
            models,
            task,
            policy=RoutingScorePolicy(cost_penalty_multiplier=100.0, max_cost_penalty=30.0),
        )

        self.assertEqual(default_selected.model.model_id, "expensive-api")
        self.assertEqual(cheap_selected.model.model_id, "cheap-local")

    def test_default_tradeoff_weights_preserve_selection_and_reasons(self):
        models = [
            ModelEndpoint(
                model_id="fast-local",
                provider="local",
                privacy_level="local",
                context_window_tokens=4096,
                average_latency_ms=100,
                capabilities={"conversation": 0.82},
            ),
            ModelEndpoint(
                model_id="slow-remote",
                provider="api",
                privacy_level="remote",
                context_window_tokens=128000,
                average_latency_ms=5000,
                input_cost_per_1k=0.004,
                output_cost_per_1k=0.012,
                capabilities={"conversation": 0.95},
            ),
        ]
        default_task = TaskProfile(task_id="chat", required_capabilities={"conversation": 0.8})
        explicit_task = TaskProfile(
            task_id="chat",
            required_capabilities={"conversation": 0.8},
            quality_tradeoff_weight=1.0,
            latency_tradeoff_weight=1.0,
            cost_tradeoff_weight=1.0,
        )

        default_selected = select_model(models, default_task)
        explicit_selected = select_model(models, explicit_task)

        self.assertEqual(explicit_selected.model.model_id, default_selected.model.model_id)
        self.assertEqual(explicit_selected.score, default_selected.score)
        self.assertEqual(explicit_selected.reasons, default_selected.reasons)

    def test_tradeoff_weights_can_change_eligible_ranking(self):
        models = [
            ModelEndpoint(
                model_id="fast-local",
                provider="local",
                privacy_level="local",
                context_window_tokens=4096,
                average_latency_ms=100,
                capabilities={"conversation": 0.82},
            ),
            ModelEndpoint(
                model_id="slow-remote",
                provider="api",
                privacy_level="remote",
                context_window_tokens=128000,
                average_latency_ms=5000,
                input_cost_per_1k=0.004,
                output_cost_per_1k=0.012,
                capabilities={"conversation": 0.95},
            ),
        ]
        default_task = TaskProfile(task_id="chat", required_capabilities={"conversation": 0.8})
        tradeoff_task = TaskProfile(
            task_id="chat",
            required_capabilities={"conversation": 0.8},
            quality_tradeoff_weight=0.4,
            latency_tradeoff_weight=3.0,
            cost_tradeoff_weight=3.0,
        )

        default_selected = select_model(models, default_task)
        tradeoff_selected = select_model(models, tradeoff_task)

        self.assertEqual(default_selected.model.model_id, "slow-remote")
        self.assertEqual(tradeoff_selected.model.model_id, "fast-local")
        self.assertTrue(
            any("tradeoff weights quality 0.40, latency 3.00, cost 3.00" in reason for reason in tradeoff_selected.reasons)
        )

    def test_latency_ceiling_blocks_slow_models(self):
        models = [
            ModelEndpoint(
                model_id="fast-local",
                provider="local",
                privacy_level="local",
                context_window_tokens=4096,
                average_latency_ms=100,
                capabilities={"conversation": 0.82},
            ),
            ModelEndpoint(
                model_id="slow-remote",
                provider="api",
                privacy_level="remote",
                context_window_tokens=128000,
                average_latency_ms=5000,
                capabilities={"conversation": 0.95},
            ),
        ]
        task = TaskProfile(
            task_id="bounded-latency-chat",
            required_capabilities={"conversation": 0.8},
            max_latency_ms=1000,
        )

        ranked = rank_models(models, task)
        slow_remote = next(score for score in ranked if score.model.model_id == "slow-remote")

        self.assertEqual(select_model(models, task).model.model_id, "fast-local")
        self.assertFalse(slow_remote.eligible)
        self.assertTrue(any("average latency 5000ms exceeds task limit 1000ms" in blocker for blocker in slow_remote.blockers))

    def test_total_cost_ceiling_blocks_expensive_models(self):
        models = [
            ModelEndpoint(
                model_id="cheap-local",
                provider="local",
                privacy_level="local",
                context_window_tokens=4096,
                average_latency_ms=1200,
                input_cost_per_1k=0.0,
                output_cost_per_1k=0.0,
                capabilities={"summarization": 0.82},
            ),
            ModelEndpoint(
                model_id="expensive-api",
                provider="api",
                privacy_level="remote",
                context_window_tokens=128000,
                average_latency_ms=1200,
                input_cost_per_1k=0.08,
                output_cost_per_1k=0.12,
                capabilities={"summarization": 0.95},
            ),
        ]
        task = TaskProfile(
            task_id="budget-summary",
            required_capabilities={"summarization": 0.8},
            max_total_cost_per_1k=0.1,
        )

        ranked = rank_models(models, task)
        expensive_api = next(score for score in ranked if score.model.model_id == "expensive-api")

        self.assertEqual(select_model(models, task).model.model_id, "cheap-local")
        self.assertFalse(expensive_api.eligible)
        self.assertTrue(any("total cost per 1k 0.2000 exceeds task limit 0.1000" in blocker for blocker in expensive_api.blockers))

    def test_score_policy_does_not_bypass_hard_blockers(self):
        task = TaskProfile(
            task_id="tool-coding",
            required_capabilities={"coding": 0.5},
            require_tools=True,
            privacy_requirement="prefer_local",
        )
        policy = RoutingScorePolicy(
            local_preference_bonus=1000.0,
            preferred_provider_bonus=1000.0,
        )

        local_rank = next(
            score
            for score in rank_models(sample_models(), task, policy=policy)
            if score.model.model_id == "local-gemma4-e4b-ultra-q8"
        )

        self.assertFalse(local_rank.eligible)
        self.assertTrue(any("tool support" in blocker for blocker in local_rank.blockers))

    def test_tradeoff_weights_do_not_bypass_hard_blockers(self):
        task = TaskProfile(
            task_id="tool-chat",
            required_capabilities={"conversation": 0.8},
            require_tools=True,
            quality_tradeoff_weight=0.2,
            latency_tradeoff_weight=5.0,
            cost_tradeoff_weight=5.0,
        )

        ranked = rank_models(sample_models(), task)
        local_rank = next(
            score
            for score in ranked
            if score.model.model_id == "local-gemma4-e4b-ultra-q8"
        )

        self.assertEqual(select_model(sample_models(), task).model.model_id, "cli-codex-high")
        self.assertFalse(local_rank.eligible)
        self.assertTrue(any("tool support" in blocker for blocker in local_rank.blockers))

    def test_routing_score_policy_metadata_tracks_custom_fields(self):
        metadata = build_routing_score_policy_metadata(
            RoutingScorePolicy(speed_bonus_weight=20.0, cost_penalty_multiplier=10.0)
        )
        payload = metadata.to_dict()

        self.assertEqual(payload["source"], "custom")
        self.assertEqual(payload["customizedFields"], ["costPenaltyMultiplier", "speedBonusWeight"])
        self.assertEqual(payload["policy"]["speedBonusWeight"], 20.0)

    def test_parse_routing_score_policy_rejects_invalid_values(self):
        with self.assertRaises(RouterError):
            parse_routing_score_policy({"schemaVersion": 1, "speedReferenceMs": 0})

    def test_rank_models_surfaces_blockers_for_ineligible_models(self):
        task = TaskProfile(
            task_id="json-memory",
            required_capabilities={"retrieval": 0.9},
            min_context_tokens=64000,
            require_json=True,
        )

        ranked = rank_models(sample_models(), task)
        local_score = next(score for score in ranked if score.model.model_id == "local-gemma4-e4b-ultra-q8")

        self.assertFalse(local_score.eligible)
        self.assertTrue(any("context window" in blocker for blocker in local_score.blockers))

    def test_character_panel_can_select_three_distinct_role_models(self):
        panel = select_character_panel(sample_models(), allow_reuse=False)

        self.assertEqual(panel.face.model.model_id, "cli-codex-high")
        self.assertEqual(panel.memory.model.model_id, "api-long-context-memory")
        self.assertEqual(panel.reasoning.model.model_id, "local-gemma4-e4b-ultra-q8")
        self.assertEqual(len({score.model.model_id for score in panel.as_dict().values()}), 3)

    def test_character_composition_supports_single_role_tertiary_symbiote(self):
        composition = select_character_composition(
            sample_models(),
            [
                CharacterRoleSpec(
                    "primary",
                    TaskProfile(
                        task_id="symbiote.tertiary.primary",
                        required_capabilities={
                            "conversation": 0.75,
                            "instruction_following": 0.75,
                        },
                        privacy_requirement="local_only",
                    ),
                    primary=True,
                )
            ],
        )

        self.assertEqual(composition.primary_role, "primary")
        self.assertEqual(list(composition.roles), ["primary"])
        self.assertEqual(composition.roles["primary"].model.model_id, "local-gemma4-e4b-ultra-q8")
        self.assertEqual(composition.max_subagents_for("primary"), 0)

    def test_character_composition_supports_large_reused_role_arrays(self):
        role_specs = [
            CharacterRoleSpec(
                "primary",
                TaskProfile(
                    task_id="kira.primary",
                    required_capabilities={"conversation": 0.85, "instruction_following": 0.85},
                ),
                primary=True,
                max_subagents=12,
            )
        ]
        for index in range(1, 8):
            role_specs.append(
                CharacterRoleSpec(
                    f"secondary-{index}",
                    TaskProfile(
                        task_id=f"kira.secondary.{index}",
                        required_capabilities={"reasoning": 0.8, "instruction_following": 0.8},
                    ),
                    max_subagents=12,
                )
            )

        composition = select_character_composition(sample_models(), role_specs, allow_reuse=True)

        self.assertEqual(composition.primary_role, "primary")
        self.assertEqual(len(composition.roles), 8)
        self.assertTrue(all(composition.max_subagents_for(role_id) == 12 for role_id in composition.roles))
        self.assertEqual(composition.roles["primary"].model.model_id, "cli-codex-high")

    def test_character_composition_rejects_duplicate_roles(self):
        role_task = TaskProfile(task_id="duplicate", required_capabilities={"conversation": 0.5})

        with self.assertRaises(RouterError) as error:
            select_character_composition(
                sample_models(),
                [
                    CharacterRoleSpec("primary", role_task, primary=True),
                    CharacterRoleSpec("primary", role_task),
                ],
            )

        self.assertIn("Duplicate CHARACTER role id", str(error.exception))

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
