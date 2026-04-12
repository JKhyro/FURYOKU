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
            process, base_url, registry_path = self._start_installed_service(temp_path)
            try:
                payload = self._wait_for_service_health(process, base_url)

                self.assertTrue(payload["ok"])
                self.assertEqual(payload["service"], "furyoku-service")
                self.assertEqual(payload["defaultRegistryPath"], str(registry_path.resolve()))
                self.assertEqual(payload["endpoints"]["serviceHealth"]["path"], "/health")
            finally:
                self._stop_process(process)

    def test_editable_install_exposes_live_provider_health_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            process, base_url, _registry_path = self._start_installed_service(temp_path)
            try:
                self._wait_for_service_health(process, base_url)
                payload = self._request_json(base_url + "/v1/health", {})

                self.assertFalse(payload["ok"])
                self.assertEqual(len(payload["providers"]), 2)
                self.assertTrue(payload["providers"][0]["ready"])
                self.assertEqual(payload["providers"][1]["status"], "missing-transport")
            finally:
                self._stop_process(process)

    def test_editable_install_exposes_live_select_and_run_endpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            process, base_url, _registry_path = self._start_installed_service(temp_path)
            task = {
                "schemaVersion": 1,
                "taskId": "private-chat",
                "privacyRequirement": "local_only",
                "requiredCapabilities": {
                    "conversation": 0.9,
                },
            }
            try:
                self._wait_for_service_health(process, base_url)
                select_payload = self._request_json(base_url + "/v1/select", {"task": task})
                run_payload = self._request_json(
                    base_url + "/v1/run",
                    {
                        "task": task,
                        "prompt": "hello",
                    },
                )

                self.assertTrue(select_payload["ok"])
                self.assertEqual(select_payload["selection"]["modelId"], "local-echo")
                self.assertEqual(select_payload["taskProfile"]["taskId"], "private-chat")

                self.assertTrue(run_payload["ok"])
                self.assertEqual(run_payload["selection"]["modelId"], "local-echo")
                self.assertEqual(run_payload["execution"]["responseText"].strip(), "echo:hello")
            finally:
                self._stop_process(process)

    def test_editable_install_exposes_service_error_payload_for_invalid_select(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            process, base_url, _registry_path = self._start_installed_service(temp_path)
            try:
                self._wait_for_service_health(process, base_url)
                error = self._request_http_error(base_url + "/v1/select", {})

                self.assertEqual(error["status"], 400)
                self.assertFalse(error["payload"]["ok"])
                self.assertEqual(error["payload"]["error"]["type"], "ServiceRequestError")
                self.assertIn("task or taskPath is required", error["payload"]["error"]["message"])
            finally:
                self._stop_process(process)

    def test_editable_install_exposes_service_error_payload_for_invalid_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            process, base_url, _registry_path = self._start_installed_service(temp_path)
            try:
                self._wait_for_service_health(process, base_url)
                error = self._request_http_error(base_url + "/v1/run", {})

                self.assertEqual(error["status"], 400)
                self.assertFalse(error["payload"]["ok"])
                self.assertEqual(error["payload"]["error"]["type"], "ServiceRequestError")
                self.assertIn("task or taskPath is required", error["payload"]["error"]["message"])
            finally:
                self._stop_process(process)

    def test_editable_install_exposes_service_error_payload_for_invalid_provider_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            process, base_url, _registry_path = self._start_installed_service(temp_path)
            try:
                self._wait_for_service_health(process, base_url)
                error = self._request_http_error(base_url + "/v1/health", {"registry": "invalid"})

                self.assertEqual(error["status"], 400)
                self.assertFalse(error["payload"]["ok"])
                self.assertEqual(error["payload"]["error"]["type"], "ServiceRequestError")
                self.assertIn("registry must be a JSON object", error["payload"]["error"]["message"])
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

    def _start_installed_service(self, temp_path: Path) -> tuple[subprocess.Popen[str], str, Path]:
        venv_dir = temp_path / "venv"
        self._install_editable_package(venv_dir)

        service_entrypoint = self._venv_service_entrypoint(venv_dir)
        self.assertTrue(service_entrypoint.exists(), msg=f"missing installed entrypoint: {service_entrypoint}")

        registry_path = temp_path / "registry.json"
        self._write_registry_fixture(registry_path)

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
        return process, f"http://127.0.0.1:{port}", registry_path

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

    def _write_registry_fixture(self, registry_path: Path) -> None:
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
                        },
                        {
                            "modelId": "remote-coder",
                            "provider": "api",
                            "privacyLevel": "remote",
                            "contextWindowTokens": 128000,
                            "averageLatencyMs": 100,
                            "supportsTools": True,
                            "capabilities": {
                                "conversation": 0.8,
                                "coding": 0.98,
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _request_json(self, url: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            return json.loads(response.read().decode("utf-8"))

    def _request_http_error(self, url: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=1)
        response = context.exception
        try:
            return {
                "status": response.code,
                "payload": json.loads(response.read().decode("utf-8")),
            }
        finally:
            response.close()

    def _wait_for_service_health(self, process: subprocess.Popen[str], base_url: str) -> dict:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(
                    "installed furyoku-service exited before answering /health: "
                    f"returncode={process.returncode}\nstdout={stdout}\nstderr={stderr}"
                )
            try:
                return self._request_json(base_url + "/health")
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
