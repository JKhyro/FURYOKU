import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

import furyoku


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_pyproject_declares_package_metadata_and_cli_entrypoint(self):
        payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(payload["project"]["name"], "furyoku")
        self.assertEqual(payload["project"]["version"], "0.1.0")
        self.assertEqual(payload["project"]["scripts"]["furyoku"], "furyoku.cli:main")
        self.assertEqual(payload["project"]["scripts"]["furyoku-service"], "furyoku.service:main")
        self.assertEqual(furyoku.__version__, payload["project"]["version"])

    def test_python_module_entrypoint_displays_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "furyoku", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("select", result.stdout)

    def test_service_module_entrypoint_displays_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "furyoku.service", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("--registry", result.stdout)


if __name__ == "__main__":
    unittest.main()
