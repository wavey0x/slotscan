import json
import unittest
from unittest.mock import patch

import httpx

from app.config import Settings
from app.main import configure_cors, create_api


class _Connection:
    async def execute(self, _statement):
        return None


class _ConnectionContext:
    async def __aenter__(self):
        return _Connection()

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return None


class _Engine:
    def connect(self):
        return _ConnectionContext()


class _Provider:
    def __init__(self, trace_response):
        self.trace_response = trace_response

    async def get_block_number(self, _chain_id):
        return 1

    async def make_request(self, _chain_id, _method, _params):
        return self.trace_response


def _health_endpoint(app):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/health"
    )


class HealthReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def _check_health(self, trace_response):
        settings = Settings(
            _env_file=None,
            RPC_URL_1="http://rpc.invalid",
        )
        provider = _Provider(trace_response)
        with (
            patch("app.main.get_settings", return_value=settings),
            patch("app.main.get_web3_provider", return_value=provider),
            patch("app.main.engine", _Engine()),
        ):
            response = await _health_endpoint(create_api())()
        return response.status_code, json.loads(response.body)

    async def test_native_trace_capability_is_required_for_readiness(self):
        status, payload = await self._check_health(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "code": -32601,
                    "message": "method not found",
                },
            }
        )

        self.assertEqual(status, 503)
        self.assertEqual(
            payload["checks"],
            {
                "database": True,
                "rpc": True,
                "native_trace": False,
            },
        )

    async def test_unhandled_errors_include_cors_headers(self):
        origin = "https://slotscan.info"
        settings = Settings(_env_file=None, CORS_ORIGINS=origin)
        with patch("app.main.get_settings", return_value=settings):
            api = create_api()

            @api.get("/test-error")
            async def test_error():
                raise RuntimeError("test failure")

            app = configure_cors(api)

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get("/test-error", headers={"Origin": origin})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)

    async def test_native_transaction_not_found_proves_readiness(self):
        status, payload = await self._check_health(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "code": -32000,
                    "message": "transaction not found",
                },
            }
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["checks"],
            {
                "database": True,
                "rpc": True,
                "native_trace": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
