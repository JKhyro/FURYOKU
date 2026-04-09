import argparse
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "benchmark_contract_report.py"
RESULTS_DIR = HERE / "results"


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


if __name__ == "__main__":
    unittest.main()
