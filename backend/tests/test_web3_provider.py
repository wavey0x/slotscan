import unittest

from app.config import Settings
from app.services.web3_provider import Web3Provider


class _RPC:
    def __init__(self, result):
        self.provider = self
        self.result = result
        self.calls = 0

    async def make_request(self, method, params):
        self.calls += 1
        return self.result


class Web3ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_rpc_error_is_returned_from_single_endpoint(self):
        manager = Web3Provider(Settings())
        rpc = _RPC({"error": {"message": "method not supported"}})
        manager._instances[1] = rpc

        result = await manager.make_request(1, "debug_traceTransaction", ["0x1"])

        self.assertEqual(result, {"error": {"message": "method not supported"}})
        self.assertEqual(rpc.calls, 1)


if __name__ == "__main__":
    unittest.main()
