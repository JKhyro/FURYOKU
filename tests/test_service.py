import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from furyoku import __version__
from furyoku.service import create_service_server


def write_registry(path: Path) -> None:
    payload = {
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
                    "instruction_following": 0.9,
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
    path.write_text(json.dumps(payload), encoding="utf-8")


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.registry_path = Path(self.temp_dir.name) / "registry.json"
        write_registry(self.registry_path)

    def _start_server(self):
        server = create_service_server(
            "127.0.0.1",
            0,
            default_registry_path=self.registry_path,
            quiet=True,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1.0)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def _request(self, base_url: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_get_health_returns_service_status(self):
        base_url = self._start_server()

        payload = self._request(base_url, "/health")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "furyoku-service")
        self.assertEqual(payload["version"], __version__)
        self.assertEqual(payload["defaultRegistryPath"], str(self.registry_path.resolve()))

    def test_post_health_returns_provider_readiness(self):
        base_url = self._start_server()

        payload = self._request(base_url, "/v1/health", {})

        self.assertFalse(payload["ok"])
        self.assertEqual(len(payload["providers"]), 2)
        self.assertTrue(payload["providers"][0]["ready"])
        self.assertEqual(payload["providers"][1]["status"], "missing-transport")

    def test_post_select_returns_selected_model(self):
        base_url = self._start_server()

        payload = self._request(
            base_url,
            "/v1/select",
            {
                "task": {
                    "schemaVersion": 1,
                    "taskId": "private-chat",
                    "privacyRequirement": "local_only",
                    "requiredCapabilities": {"conversation": 0.9},
                }
            },
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selection"]["modelId"], "local-echo")
        self.assertEqual(payload["taskProfile"]["taskId"], "private-chat")

    def test_post_run_executes_selected_model(self):
        base_url = self._start_server()

        payload = self._request(
            base_url,
            "/v1/run",
            {
                "task": {
                    "schemaVersion": 1,
                    "taskId": "private-chat",
                    "privacyRequirement": "local_only",
                    "requiredCapabilities": {"conversation": 0.9},
                },
                "prompt": "hello",
            },
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selection"]["modelId"], "local-echo")
        self.assertEqual(payload["execution"]["responseText"].strip(), "echo:hello")

    def test_post_select_rejects_missing_task(self):
        base_url = self._start_server()
        request = urllib.request.Request(
            base_url + "/v1/select",
            data=json.dumps({}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=10)

        self.assertEqual(context.exception.code, 400)
        payload = json.loads(context.exception.read().decode("utf-8"))
        context.exception.close()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "ServiceRequestError")


if __name__ == "__main__":
    unittest.main()
