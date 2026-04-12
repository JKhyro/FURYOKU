import json
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import urllib.error
import urllib.request
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
            self._install_editable_package(venv_dir)

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

    def test_editable_install_exposes_live_service_health_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            venv_dir = temp_path / "venv"
            self._install_editable_package(venv_dir)

            service_entrypoint = self._venv_service_entrypoint(venv_dir)
            self.assertTrue(service_entrypoint.exists(), msg=f"missing installed entrypoint: {service_entrypoint}")

            registry_path = temp_path / "registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "models": [
                            {
                                "modelId": "local-echo",
                                "provider": "local",
                                "privacyLevel": "local",
                                "contextWindowTokens": 4096,
                                "averageLatencyMs": 10,
                                "invocation": [
                                    sys.executable,
                                    "-c",
                                    "import sys; print('echo:' + sys.stdin.read())",
                                ],
                                "capabilities": {
                                    "conversation": 0.95,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            port = self._find_free_port()
            process = subprocess.Popen(
                [
                    str(service_entrypoint),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--registry",
                    str(registry_path),
                    "--quiet",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                payload = self._wait_for_service_health(process, port)

                self.assertTrue(payload["ok"])
                self.assertEqual(payload["service"], "furyoku-service")
                self.assertEqual(payload["defaultRegistryPath"], str(registry_path.resolve()))
                self.assertEqual(payload["endpoints"]["serviceHealth"]["path"], "/health")
            finally:
                self._stop_process(process)

    def _install_editable_package(self, venv_dir: Path) -> None:
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

    def _venv_python(self, venv_dir: Path) -> Path:
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _venv_service_entrypoint(self, venv_dir: Path) -> Path:
        if sys.platform == "win32":
            return venv_dir / "Scripts" / "furyoku-service.exe"
        return venv_dir / "bin" / "furyoku-service"

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def _wait_for_service_health(self, process: subprocess.Popen[str], port: int) -> dict:
        deadline = time.monotonic() + 15
        url = f"http://127.0.0.1:{port}/health"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(
                    "installed furyoku-service exited before answering /health: "
                    f"returncode={process.returncode}\nstdout={stdout}\nstderr={stderr}"
                )
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError:
                time.sleep(0.1)

        stdout, stderr = self._stop_process(process)
        self.fail(
            "installed furyoku-service did not answer /health before timeout: "
            f"stdout={stdout}\nstderr={stderr}"
        )

    def _stop_process(self, process: subprocess.Popen[str]) -> tuple[str, str]:
        if process.poll() is not None:
            return process.communicate()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return process.communicate()


if __name__ == "__main__":
    unittest.main()
