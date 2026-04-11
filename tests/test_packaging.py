import subprocess
import sys
import tempfile
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

    def test_editable_install_exposes_service_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            venv_dir = Path(temp_dir) / "venv"
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            venv_python = self._venv_python(venv_dir)
            install_result = subprocess.run(
                [str(venv_python), "-m", "pip", "install", "-e", str(ROOT)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(install_result.returncode, 0, msg=install_result.stderr)

            service_entrypoint = self._venv_service_entrypoint(venv_dir)
            self.assertTrue(service_entrypoint.exists(), msg=f"missing installed entrypoint: {service_entrypoint}")

            help_result = subprocess.run(
                [str(service_entrypoint), "--help"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(help_result.returncode, 0, msg=help_result.stderr)
            self.assertIn("usage:", help_result.stdout)
            self.assertIn("--registry", help_result.stdout)

    def _venv_python(self, venv_dir: Path) -> Path:
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _venv_service_entrypoint(self, venv_dir: Path) -> Path:
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "furyoku-service.exe"
        return venv_dir / "bin" / "furyoku-service"


if __name__ == "__main__":
    unittest.main()
