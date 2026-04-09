import argparse
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "benchmark_contract_report.py"
RESULTS_DIR = HERE / "results"
PROFILES_PATH = HERE / "machine_profiles.json"


def load_module():
    spec = importlib.util.spec_from_file_location("benchmark_contract_report", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BenchmarkContractReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = load_module()
        cls.args = argparse.Namespace(
            baseline_model=[],
            candidate_model=[],
            title="Regression Check",
            decision=None,
            decision_reason=None,
            machine_profile_path="",
            machine_profile_name="",
            machine_profile_label="",
            profile_system_memory_mb=0,
            profile_gpu_memory_mb=0,
        )

    def load_payload(self, name: str) -> dict:
        return self.report.load_json(RESULTS_DIR / name)

    def test_response_suite_exposes_composite_resource_fit_block(self):
        payload = self.load_payload("2026-04-09-gemma3-heretic-compare-response-suite.json")
        evaluated = self.report.evaluate_results(payload, "response-suite.json", self.args)

        q4_compare = evaluated["compareDecision"]["models"]["gemma3-heretic:4b-q4km"]
        q5_compare = evaluated["compareDecision"]["models"]["gemma3-heretic:4b-q5km"]
        q5_resource = evaluated["resourceFitVerdict"]["models"]["gemma3-heretic:4b-q5km"]

        self.assertEqual(q4_compare["status"], "retain-baseline")
        self.assertEqual(q5_compare["status"], "candidate-blocked-contract-and-machine-fit")
        self.assertEqual(q5_resource["status"], "blocked")
        self.assertIn(
            "resource_fit:gpu_headroom",
            {failure["id"] for failure in q5_resource["blockingFailures"]},
        )

    def test_auto_verdict_names_blocked_candidate_for_composite_status(self):
        summaries = []
        for name in [
            "2026-04-09-gemma3-heretic-compare-benchmark.json",
            "2026-04-09-gemma3-heretic-compare-response-suite.json",
            "2026-04-09-gemma3-heretic-compare-sexual-boundary.json",
            "2026-04-09-gemma3-heretic-compare-advanced-suite.json",
        ]:
            payload = self.load_payload(name)
            evaluated = self.report.evaluate_results(payload, name, self.args)
            summaries.extend(self.report.summarize_input(RESULTS_DIR / name, evaluated))

        summary = self.report.build_summary_markdown(summaries, self.args)

        self.assertIn("Retain `gemma3-heretic:4b-q4km` as the deployed local baseline.", summary)
        self.assertIn(
            "Comparison candidates `gemma3-heretic:4b-q5km` are blocked from promotion by the current contract and machine-fit gates.",
            summary,
        )
        self.assertIn("| `gemma3-heretic:4b-q5km` | `candidate` | `candidate-blocked-contract-and-machine-fit` |", summary)

    def test_baseline_compare_status_flips_to_at_risk_when_resource_fit_is_not_fit(self):
        verdict = self.report.build_compare_verdict(
            "gemma3-heretic:4b-q4km",
            "baseline",
            {"status": "blocked", "promotable": False},
            ["gemma3-heretic:4b-q4km"],
            {
                "status": "blocked",
                "promotable": False,
                "summary": "Baseline exceeds the preferred local machine-fit envelope.",
                "metrics": {"peakGpuMemoryUsedMb": 3980},
                "blockingFailures": [
                    {
                        "id": "resource_fit:gpu_headroom",
                        "severity": "blocker",
                        "reason": "GPU headroom falls too close to the VRAM ceiling.",
                    }
                ],
                "degradations": [],
            },
        )

        self.assertEqual(verdict["status"], "retain-baseline-at-risk")
        self.assertTrue(verdict["baselineAtRisk"])
        self.assertEqual(verdict["baselineRiskStatus"], "blocked")
        self.assertIn("least-bad current option", verdict["summary"])
        self.assertIn("resource_fit:gpu_headroom", {reason["id"] for reason in verdict["baselineRiskReasons"]})

    def test_auto_verdict_marks_retained_baseline_as_at_risk(self):
        decision, reason = self.report.build_auto_verdict(
            [
                {
                    "model": "gemma3-heretic:4b-q4km",
                    "role": "baseline",
                    "status": "retain-baseline-at-risk",
                },
                {
                    "model": "gemma3-heretic:4b-q5km",
                    "role": "candidate",
                    "status": "candidate-blocked-contract-and-machine-fit",
                },
            ]
        )

        self.assertIn("treat it as at risk", decision)
        self.assertIn("least-bad current option", reason)

    def test_profile_overrides_can_flip_baseline_to_at_risk(self):
        payload = self.load_payload("2026-04-09-gemma3-heretic-compare-response-suite.json")
        override_args = argparse.Namespace(
            baseline_model=[],
            candidate_model=[],
            title="Override Check",
            decision=None,
            decision_reason=None,
            machine_profile_path="",
            machine_profile_name="",
            machine_profile_label="28 GB RAM / 3.5 GB VRAM local profile",
            profile_system_memory_mb=28672,
            profile_gpu_memory_mb=3584,
        )

        evaluated = self.report.evaluate_results(payload, "response-suite.json", override_args)
        q4_resource = evaluated["resourceFitVerdict"]["models"]["gemma3-heretic:4b-q4km"]
        q4_compare = evaluated["compareDecision"]["models"]["gemma3-heretic:4b-q4km"]

        self.assertEqual(q4_resource["machineProfile"]["label"], "28 GB RAM / 3.5 GB VRAM local profile")
        self.assertEqual(q4_resource["machineProfile"]["gpuMemoryMb"], 3584)
        self.assertEqual(q4_resource["status"], "blocked")
        self.assertIn("28 GB RAM / 3.5 GB VRAM local profile", q4_resource["summary"])
        self.assertIn("3.5 GB VRAM ceiling", q4_resource["blockingFailures"][0]["reason"])
        self.assertEqual(q4_compare["status"], "retain-baseline-at-risk")

    def test_profile_presets_load_from_shared_json_file(self):
        payload = self.load_payload("2026-04-09-gemma3-heretic-compare-response-suite.json")
        preset_args = argparse.Namespace(
            baseline_model=[],
            candidate_model=[],
            title="Preset Check",
            decision=None,
            decision_reason=None,
            machine_profile_path=str(PROFILES_PATH),
            machine_profile_name="tight-28gb-3.5gb",
            machine_profile_label="",
            profile_system_memory_mb=0,
            profile_gpu_memory_mb=0,
        )

        evaluated = self.report.evaluate_results(payload, "response-suite.json", preset_args)
        top_resource_profile = evaluated["resourceFitVerdict"]["machineProfile"]
        top_compare_profile = evaluated["compareDecision"]["machineProfile"]
        q4_resource = evaluated["resourceFitVerdict"]["models"]["gemma3-heretic:4b-q4km"]
        q4_compare = evaluated["compareDecision"]["models"]["gemma3-heretic:4b-q4km"]

        self.assertEqual(top_resource_profile["presetName"], "tight-28gb-3.5gb")
        self.assertEqual(top_compare_profile["presetName"], "tight-28gb-3.5gb")
        self.assertEqual(top_resource_profile["presetPath"], "benchmarks/openclaw-local-llm/machine_profiles.json")
        self.assertEqual(q4_resource["machineProfile"]["presetSource"], "preset-file")
        self.assertEqual(q4_resource["machineProfile"]["presetPath"], "benchmarks/openclaw-local-llm/machine_profiles.json")
        self.assertEqual(q4_compare["machineProfile"]["presetName"], "tight-28gb-3.5gb")
        self.assertEqual(q4_compare["status"], "retain-baseline-at-risk")

    def test_absolute_preset_paths_outside_repo_collapse_to_file_name(self):
        profile = self.report.normalize_machine_profile(
            "external-profile",
            {
                "label": "External preset",
                "systemMemoryMb": 32768,
                "gpuMemoryMb": 4096,
            },
            Path(r"C:\temp\custom_profiles.json"),
        )

        self.assertEqual(profile["presetPath"], "custom_profiles.json")

    def test_summary_mentions_resolved_preset_identity(self):
        payload = self.load_payload("2026-04-09-gemma3-heretic-compare-response-suite.json")
        preset_args = argparse.Namespace(
            baseline_model=[],
            candidate_model=[],
            title="Preset Summary",
            decision=None,
            decision_reason=None,
            machine_profile_path=str(PROFILES_PATH),
            machine_profile_name="tight-28gb-3.5gb",
            machine_profile_label="",
            profile_system_memory_mb=0,
            profile_gpu_memory_mb=0,
        )

        evaluated = self.report.evaluate_results(payload, "response-suite.json", preset_args)
        summary = self.report.build_summary_markdown(
            self.report.summarize_input(RESULTS_DIR / "2026-04-09-gemma3-heretic-compare-response-suite.json", evaluated),
            preset_args,
        )

        self.assertIn("Preset identity: `tight-28gb-3.5gb` (preset-file).", summary)


if __name__ == "__main__":
    unittest.main()
