import unittest

from app.main import create_api


class ApiSurfaceTests(unittest.TestCase):
    def test_only_current_contract_storage_and_transaction_routes_are_exposed(self):
        paths = set(create_api().openapi()["paths"])

        self.assertIn(
            "/api/slotscan/contracts/{chain_id}/{address}/storage-view",
            paths,
        )
        self.assertIn("/api/slotscan/storage/query", paths)
        self.assertIn(
            "/api/slotscan/layout-comparisons/{chain_id}",
            paths,
        )
        self.assertIn("/api/slotscan/tx/{chain_id}/{tx_hash}", paths)
        obsolete = {
            "/api/slotscan/contracts/{chain_id}/{address}",
            "/api/slotscan/contracts/{chain_id}/{address}/layout",
            "/api/slotscan/storage/{chain_id}/{address}",
            "/api/slotscan/storage/{chain_id}/{address}/slot/{slot}",
            "/api/slotscan/tx/{chain_id}/{address}/{tx_hash}",
        }
        self.assertTrue(paths.isdisjoint(obsolete))

    def test_transaction_response_has_no_internal_generation(self):
        schema = create_api().openapi()["components"]["schemas"][
            "TransactionStorageHistoryResponse"
        ]

        self.assertNotIn("analysis_version", schema["properties"])

    def test_comparison_response_has_no_schema_version(self):
        schema = create_api().openapi()["components"]["schemas"][
            "LayoutComparisonResponse"
        ]

        self.assertNotIn("schema_version", schema["properties"])


if __name__ == "__main__":
    unittest.main()
