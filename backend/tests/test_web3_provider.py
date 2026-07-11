import unittest

from app.config import Settings
from app.services.web3_provider import Web3Provider


class _RPC:
    def __init__(self, result):
        self.provider = self
        self.result = result

    async def make_request(self, method, params):
        return self.result


class Web3FailoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_rpc_error_falls_through_to_backup(self):
        manager = Web3Provider(Settings())
        primary = _RPC({"error": {"message": "method not supported"}})
        backup = _RPC({"result": {"structLogs": []}})
        manager._providers = lambda chain_id: [primary, backup]
        result = await manager.make_request(1, "debug_traceTransaction", ["0x1"])
        self.assertEqual(result, {"result": {"structLogs": []}})


if __name__ == "__main__":
    unittest.main()
