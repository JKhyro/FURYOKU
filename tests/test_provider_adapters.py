import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading
import unittest

from furyoku import (
    ApiProviderAdapter,
    ModelEndpoint,
    ProviderAdapterError,
    ProviderExecutionRequest,
    SubprocessProviderAdapter,
    TaskProfile,
    execute_model,
    execute_selected_model,
    select_model,
)


def local_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="local-echo",
        provider="local",
        privacy_level="local",
        context_window_tokens=4096,
        average_latency_ms=10,
        invocation=("echo-model", "--json"),
        capabilities={"conversation": 1.0, "instruction_following": 1.0},
        supports_json=True,
    )


def cli_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="cli-coder",
        provider="cli",
        privacy_level="remote",
        context_window_tokens=128000,
        average_latency_ms=20,
        invocation=("codex", "--model", "test"),
        capabilities={"coding": 1.0, "reasoning": 1.0},
        supports_tools=True,
    )


def api_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="api-memory",
        provider="api",
        privacy_level="remote",
        context_window_tokens=200000,
        average_latency_ms=30,
        capabilities={"retrieval": 1.0, "summarization": 1.0},
        supports_json=True,
    )


class ProviderAdapterTests(unittest.TestCase):
    def test_subprocess_adapter_success_captures_stdout_and_exit_code(self):
        calls = []

        def runner(invocation, prompt, timeout):
            calls.append((invocation, prompt, timeout))
            return subprocess.CompletedProcess(invocation, 0, stdout="model response", stderr="")

        result = SubprocessProviderAdapter(runner).execute(
            local_endpoint(),
            ProviderExecutionRequest("hello", timeout_seconds=3.0),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.response_text, "model response")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.model_id, "local-echo")
        self.assertEqual(calls, [((("echo-model", "--json")), "hello", 3.0)])

    def test_subprocess_adapter_decodes_utf8_model_output(self):
        endpoint = ModelEndpoint(
            model_id="utf8-local",
            provider="local",
            capabilities={"conversation": 1.0},
            context_window_tokens=4096,
            average_latency_ms=10,
            invocation=(
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write('unicode model response: \\U0001f642'.encode('utf-8'))",
            ),
        )

        result = SubprocessProviderAdapter().execute(endpoint, ProviderExecutionRequest("hello"))

        self.assertTrue(result.ok)
        self.assertIn("unicode model response", result.response_text)
        self.assertIn("\U0001f642", result.response_text)

    def test_subprocess_adapter_nonzero_returns_error_result(self):
        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 2, stdout="", stderr="bad prompt")

        result = SubprocessProviderAdapter(runner).execute(
            cli_endpoint(),
            ProviderExecutionRequest("hello"),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.stderr, "bad prompt")
        self.assertIn("code 2", result.error)

    def test_subprocess_adapter_timeout_returns_timeout_result(self):
        def runner(invocation, prompt, timeout):
            raise subprocess.TimeoutExpired(invocation, timeout, output=b"partial", stderr=b"late")

        result = SubprocessProviderAdapter(runner).execute(
            local_endpoint(),
            ProviderExecutionRequest("hello", timeout_seconds=0.01),
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.response_text, "partial")
        self.assertEqual(result.stderr, "late")

    def test_execute_model_rejects_unsupported_provider(self):
        endpoint = ModelEndpoint(
            model_id="unknown",
            provider="browser",
            capabilities={"conversation": 1.0},
            context_window_tokens=1000,
            average_latency_ms=10,
        )

        with self.assertRaises(ProviderAdapterError) as error:
            execute_model(endpoint, "hello")

        self.assertIn("Unsupported provider", str(error.exception))

    def test_api_adapter_success_uses_injected_transport(self):
        def transport(endpoint, request):
            return {"response_text": f"{endpoint.model_id}: {request.prompt}", "status": "ok"}

        result = ApiProviderAdapter(transport).execute(
            api_endpoint(),
            ProviderExecutionRequest("retrieve memory"),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.response_text, "api-memory: retrieve memory")
        self.assertEqual(result.provider, "api")

    def test_api_adapter_executes_registry_configured_openai_compatible_endpoint(self):
        seen_requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                seen_requests.append((self.path, self.headers.get("Authorization"), payload))
                response = {
                    "choices": [
                        {"message": {"content": f"api:{payload['messages'][0]['content']}"}}
                    ]
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        old_key = os.environ.get("FURYOKU_TEST_API_KEY")
        os.environ["FURYOKU_TEST_API_KEY"] = "test-secret"
        self.addCleanup(
            lambda: os.environ.pop("FURYOKU_TEST_API_KEY", None)
            if old_key is None
            else os.environ.__setitem__("FURYOKU_TEST_API_KEY", old_key)
        )
        endpoint = ModelEndpoint(
            model_id="api-configured",
            provider="api",
            capabilities={"conversation": 1.0},
            context_window_tokens=128000,
            average_latency_ms=20,
            metadata={
                "apiUrl": f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                "apiKeyEnv": "FURYOKU_TEST_API_KEY",
                "apiModel": "remote-model",
            },
        )

        result = ApiProviderAdapter().execute(endpoint, ProviderExecutionRequest("hello"))

        self.assertTrue(result.ok)
        self.assertEqual(result.response_text, "api:hello")
        self.assertEqual(seen_requests[0][0], "/v1/chat/completions")
        self.assertEqual(seen_requests[0][1], "Bearer test-secret")
        self.assertEqual(seen_requests[0][2]["model"], "remote-model")

    def test_api_adapter_missing_configured_api_key_is_observable_error(self):
        endpoint = ModelEndpoint(
            model_id="api-configured",
            provider="api",
            capabilities={"conversation": 1.0},
            context_window_tokens=128000,
            average_latency_ms=20,
            metadata={"apiUrl": "http://127.0.0.1:9/test", "apiKeyEnv": "FURYOKU_TEST_MISSING_KEY"},
        )

        result = ApiProviderAdapter().execute(endpoint, ProviderExecutionRequest("hello"))

        self.assertFalse(result.ok)
        self.assertIn("FURYOKU_TEST_MISSING_KEY", result.error)

    def test_api_adapter_failure_returns_error_result(self):
        def transport(endpoint, request):
            raise RuntimeError("api unavailable")

        result = ApiProviderAdapter(transport).execute(
            api_endpoint(),
            ProviderExecutionRequest("retrieve memory"),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error, "api unavailable")

    def test_execute_selected_model_runs_router_selected_endpoint(self):
        models = [local_endpoint(), cli_endpoint()]
        selection = select_model(
            models,
            TaskProfile("private-chat", {"conversation": 0.9}, privacy_requirement="local_only"),
        )

        def runner(invocation, prompt, timeout):
            return subprocess.CompletedProcess(invocation, 0, stdout=f"selected: {prompt}", stderr="")

        result = execute_selected_model(
            selection,
            "hello",
            adapters={"local": SubprocessProviderAdapter(runner)},
        )

        self.assertEqual(result.model_id, "local-echo")
        self.assertEqual(result.response_text, "selected: hello")
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
