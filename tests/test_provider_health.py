import unittest

from furyoku import (
    ModelEndpoint,
    ProviderHealthCheckRequest,
    check_provider_health,
    check_provider_health_many,
)


def local_endpoint(invocation=("furyoku-local", "--probe")) -> ModelEndpoint:
    return ModelEndpoint(
        model_id="local-ready",
        provider="local",
        privacy_level="local",
        context_window_tokens=4096,
        average_latency_ms=10,
        invocation=invocation,
        capabilities={"conversation": 1.0},
    )


def api_endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        model_id="api-ready",
        provider="api",
        privacy_level="remote",
        context_window_tokens=128000,
        average_latency_ms=20,
        capabilities={"conversation": 1.0},
    )


def configured_api_endpoint(**metadata) -> ModelEndpoint:
    return ModelEndpoint(
        model_id="api-configured",
        provider="api",
        privacy_level="remote",
        context_window_tokens=128000,
        average_latency_ms=20,
        capabilities={"conversation": 1.0},
        metadata={"apiUrl": "http://127.0.0.1:9/test", **metadata},
    )


class ProviderHealthTests(unittest.TestCase):
    def test_local_command_ready_without_probe(self):
        result = check_provider_health(
            local_endpoint(),
            command_resolver=lambda command: f"C:/tools/{command}.exe",
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.command, "furyoku-local")
        self.assertEqual(result.resolved_command, "C:/tools/furyoku-local.exe")
        self.assertIsNone(result.execution)

    def test_local_missing_command(self):
        result = check_provider_health(
            local_endpoint(),
            command_resolver=lambda command: None,
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "missing-command")
        self.assertEqual(result.command, "furyoku-local")
        self.assertIn("furyoku-local", result.reason)

    def test_local_missing_invocation(self):
        result = check_provider_health(
            local_endpoint(invocation=()),
            command_resolver=lambda command: f"C:/tools/{command}.exe",
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "missing-invocation")
        self.assertIsNone(result.command)

    def test_api_no_transport(self):
        result = check_provider_health(api_endpoint())

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "missing-transport")
        self.assertIn("transport", result.reason)

    def test_api_configured_transport_ready_without_probe(self):
        result = check_provider_health(configured_api_endpoint())

        self.assertTrue(result.ready)
        self.assertEqual(result.status, "ready")
        self.assertIn("configuration", result.reason)

    def test_api_configured_transport_missing_key_env_is_not_ready(self):
        result = check_provider_health(configured_api_endpoint(apiKeyEnv="FURYOKU_TEST_MISSING_KEY"))

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "missing-credential")
        self.assertIn("FURYOKU_TEST_MISSING_KEY", result.reason)

    def test_api_probe_success_uses_injected_transport(self):
        calls = []

        def transport(endpoint, request):
            calls.append((endpoint.model_id, request.prompt, request.timeout_seconds, request.metadata))
            return {"status": "ok", "response_text": "healthy"}

        result = check_provider_health(
            api_endpoint(),
            ProviderHealthCheckRequest(
                probe=True,
                probe_prompt="health",
                timeout_seconds=1.5,
                metadata={"check": "provider-health"},
            ),
            api_transport=transport,
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.status, "ready")
        self.assertIsNotNone(result.execution)
        self.assertTrue(result.execution.ok)
        self.assertEqual(result.execution.response_text, "healthy")
        self.assertEqual(calls, [("api-ready", "health", 1.5, {"check": "provider-health"})])

    def test_api_probe_failure_reports_not_ready(self):
        def transport(endpoint, request):
            raise RuntimeError("api unavailable")

        result = check_provider_health(
            api_endpoint(),
            ProviderHealthCheckRequest(probe=True, probe_prompt="health"),
            api_transport=transport,
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "probe-failed")
        self.assertIsNotNone(result.execution)
        self.assertEqual(result.execution.status, "error")
        self.assertEqual(result.reason, "api unavailable")

    def test_aggregate_checks_preserve_endpoint_order(self):
        endpoints = [
            local_endpoint(),
            local_endpoint(invocation=("missing-model",)),
            local_endpoint(invocation=()),
        ]

        results = check_provider_health_many(
            endpoints,
            command_resolver=lambda command: "C:/tools/furyoku-local.exe"
            if command == "furyoku-local"
            else None,
        )

        self.assertEqual([result.model_id for result in results], ["local-ready", "local-ready", "local-ready"])
        self.assertEqual([result.status for result in results], ["ready", "missing-command", "missing-invocation"])
        self.assertEqual([result.ready for result in results], [True, False, False])


if __name__ == "__main__":
    unittest.main()
