import unittest
from unittest.mock import patch

from app.config import Settings
from app.models.errors import CompilationError
from app.services.layout import LayoutParser


class CompilerArtifactTests(unittest.TestCase):
    def test_standard_input_retains_ast_storage_and_transient_layouts(self):
        parser = LayoutParser()
        standard_input = parser.build_solidity_standard_input(
            {"C.sol": "contract C {}"},
            {"optimizer": {"enabled": True, "runs": 200}},
        )
        selection = standard_input["settings"]["outputSelection"]["*"]
        self.assertEqual(selection[""], ["ast"])
        self.assertEqual(
            selection["*"],
            ["storageLayout", "transientStorageLayout"],
        )

    def test_fingerprint_covers_exact_compiler_input(self):
        parser = LayoutParser()
        first_input = parser.build_solidity_standard_input(
            {"C.sol": "contract C {}"}, None
        )
        second_input = parser.build_solidity_standard_input(
            {"C.sol": "contract C { uint x; }"}, None
        )
        first = parser.artifact_fingerprint(
            language="Solidity",
            compiler_version="v0.8.30+commit.73712a01",
            pipeline="solc-standard-json",
            standard_input=first_input,
        )
        repeated = parser.artifact_fingerprint(
            language="Solidity",
            compiler_version="v0.8.30+commit.73712a01",
            pipeline="solc-standard-json",
            standard_input=first_input,
        )
        changed = parser.artifact_fingerprint(
            language="Solidity",
            compiler_version="v0.8.30+commit.73712a01",
            pipeline="solc-standard-json",
            standard_input=second_input,
        )
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, changed)


class CompilerPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_time_install_is_disabled_by_default(self):
        parser = LayoutParser(Settings(ALLOW_COMPILER_INSTALL=False))
        with patch("app.services.layout.solcx.get_installed_solc_versions", return_value=[]):
            with self.assertRaisesRegex(CompilationError, "installation is disabled"):
                await parser._ensure_solc_version("0.8.30")


if __name__ == "__main__":
    unittest.main()
