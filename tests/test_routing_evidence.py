import unittest
from pathlib import Path

from furyoku import (
    RoutingEvidenceError,
    load_routing_evidence_contract,
    parse_routing_evidence_contract,
)


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    ROOT
    / "benchmarks"
    / "openclaw-local-llm"
    / "results"
    / "2026-04-13-approved-ready-current-baseline.json"
)
BLOCKED_ROSTER_PATH = (
    ROOT
    / "benchmarks"
    / "openclaw-local-llm"
    / "results"
    / "2026-04-13-approved-blocked-roster-probe.json"
)


class RoutingEvidenceContractTests(unittest.TestCase):
    def test_loads_current_baseline_and_blocked_roster(self):
        contract = load_routing_evidence_contract(
            BASELINE_PATH,
            blocked_roster_path=BLOCKED_ROSTER_PATH,
        )

        self.assertEqual(contract.selected_baseline_model, "gemma4-e4b-ultra-heretic:q8_0")
        self.assertEqual(contract.machine_profile["presetName"], "default-32gb-4gb")
        self.assertIn("gemma4-e4b-ultra-heretic:q8_0", contract.models)
        self.assertIn("gemma4-31b-heretic:q4_k_m", contract.blocked_roster)

    def test_retained_baseline_at_risk_is_not_promoted(self):
        contract = load_routing_evidence_contract(
            BASELINE_PATH,
            blocked_roster_path=BLOCKED_ROSTER_PATH,
        )
        baseline = contract.models["gemma4-e4b-ultra-heretic:q8_0"]

        self.assertEqual(baseline.routing_directive, "retain-baseline-at-risk")
        self.assertTrue(baseline.retained_baseline_at_risk)
        self.assertTrue(baseline.contract_blocked)
        self.assertTrue(baseline.resource_blocked)
        self.assertIn("gemma4-e4b-ultra-heretic:q8_0", contract.retained_model_ids)
        self.assertNotIn("gemma4-e4b-ultra-heretic:q8_0", contract.blocked_model_ids)

    def test_blocked_candidates_do_not_promote(self):
        contract = load_routing_evidence_contract(BASELINE_PATH)
        candidate = contract.models["gemma4-e2b-hauhau-aggressive:q8kp"]

        self.assertEqual(candidate.routing_directive, "do-not-promote")
        self.assertIn("route_decision:expected_route_decision", candidate.hard_blocker_ids)
        self.assertEqual(
            contract.routing_directive_for("gemma4-e2b-hauhau-aggressive:q8kp"),
            "do-not-promote",
        )

    def test_blocked_roster_excludes_heavy_models(self):
        contract = load_routing_evidence_contract(
            BASELINE_PATH,
            blocked_roster_path=BLOCKED_ROSTER_PATH,
        )

        self.assertEqual(contract.routing_directive_for("gemma4-31b-heretic:q4_k_m"), "exclude")
        self.assertIn("gemma4-31b-heretic:q4_k_m", contract.blocked_model_ids)

    def test_contract_dict_declares_non_bypass_rules(self):
        contract = load_routing_evidence_contract(BASELINE_PATH)
        payload = contract.to_dict()

        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["routingSemantics"]["authority"], "evidence-only")
        self.assertIn("provider_health", payload["routingSemantics"]["mustNotBypass"])
        self.assertIn("duplicate_execution_guard", payload["routingSemantics"]["mustNotBypass"])

    def test_rejects_unsupported_schema(self):
        with self.assertRaises(RoutingEvidenceError):
            parse_routing_evidence_contract({"schemaVersion": 99, "models": {}}, source="bad")

    def test_rejects_mismatched_model_key(self):
        with self.assertRaises(RoutingEvidenceError):
            parse_routing_evidence_contract(
                {
                    "schemaVersion": 1,
                    "models": {
                        "expected": {
                            "model": "actual",
                            "role": "candidate",
                            "compareDecision": "retain-baseline",
                        }
                    },
                },
                source="bad",
            )


if __name__ == "__main__":
    unittest.main()
