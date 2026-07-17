import unittest

from app.main import create_app


class ApiSurfaceTests(unittest.TestCase):
    def test_only_transaction_wide_route_is_exposed(self):
        paths = set(create_app().openapi()["paths"])

        self.assertIn("/api/slotscan/tx/{chain_id}/{tx_hash}", paths)
        self.assertNotIn(
            "/api/slotscan/tx/{chain_id}/{address}/{tx_hash}",
            paths,
        )

    def test_transaction_response_has_no_internal_generation(self):
        schema = create_app().openapi()["components"]["schemas"][
            "TransactionStorageHistoryResponse"
        ]

        self.assertNotIn("analysis_version", schema["properties"])


if __name__ == "__main__":
    unittest.main()
