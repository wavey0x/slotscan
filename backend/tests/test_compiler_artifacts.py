import unittest
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.models.errors import CompilationError
from app.services.layout import LayoutParser


class _FakeReader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    async def read(self, size):
        chunk = self.data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class _FakeStdin:
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data

    async def drain(self):
        return None

    def close(self):
        return None

    async def wait_closed(self):
        return None


class _FakeProcess:
    def __init__(self, stdout, stderr=b""):
        self.stdin = _FakeStdin()
        self.stdout = _FakeReader(stdout)
        self.stderr = _FakeReader(stderr)
        self.returncode = None
        self.killed = False
        self.waited = False

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        self.returncode = -9 if self.killed else 0
        return self.returncode


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

    def test_solidity_target_selection_is_exact_and_unambiguous(self):
        parser = LayoutParser()
        output = {
            "contracts": {
                "A.sol": {"Vault": {"storageLayout": {"storage": ["a"]}}},
                "B.sol": {
                    "Vault": {"storageLayout": {"storage": ["b"]}},
                    "VaultHelper": {"storageLayout": {"storage": ["helper"]}},
                },
            }
        }

        self.assertEqual(
            parser._extract_layout("Vault", output, "B.sol:Vault"),
            {"storage": ["b"]},
        )
        with self.assertRaisesRegex(CompilationError, "Ambiguous contract name"):
            parser._extract_layout("Vault", output)
        with self.assertRaises(Exception):
            parser._extract_layout("VaultHelp", output)


class VyperTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_vyper_target_requires_an_exact_or_unique_entry_source(self):
        parser = LayoutParser()
        sources = {
            "A.vy": "# @version 0.3.10\n",
            "B.vy": "# @version 0.3.10\n",
        }

        with self.assertRaisesRegex(CompilationError, "Ambiguous Vyper entry source"):
            await parser.parse_vyper_with_artifact(
                "A",
                sources,
                "0.3.10",
            )
        with self.assertRaisesRegex(CompilationError, "entry source not found"):
            await parser.parse_vyper_with_artifact(
                "A",
                sources,
                "0.3.10",
                entry_source="Missing.vy",
            )


class CompilerPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_time_install_is_disabled_by_default(self):
        parser = LayoutParser(Settings(ALLOW_COMPILER_INSTALL=False))
        with patch("app.services.layout.solcx.get_installed_solc_versions", return_value=[]):
            with self.assertRaisesRegex(CompilationError, "installation is disabled"):
                await parser._ensure_solc_version("0.8.30")

    async def test_compiler_output_limit_kills_and_reaps_process(self):
        cases = (
            (
                "stdout",
                b"{" + b"x" * 8,
                b"",
                {"MAX_COMPILER_STDOUT_BYTES": 8},
            ),
            (
                "stderr",
                b'{"contracts":{}}',
                b"x" * 9,
                {"MAX_COMPILER_STDERR_BYTES": 8},
            ),
        )
        for stream, stdout, stderr, settings in cases:
            with self.subTest(stream=stream):
                process = _FakeProcess(stdout, stderr)
                parser = LayoutParser(Settings(**settings))
                with (
                    patch(
                        "app.services.layout.get_executable",
                        return_value="/usr/bin/solc",
                    ),
                    patch(
                        "app.services.layout.asyncio.create_subprocess_exec",
                        new=AsyncMock(return_value=process),
                    ),
                ):
                    with self.assertRaisesRegex(
                        CompilationError,
                        f"{stream} exceeded 8 bytes",
                    ):
                        await parser._run_solc_standard_json(
                            "0.8.30",
                            {"language": "Solidity"},
                        )

                self.assertTrue(process.killed)
                self.assertTrue(process.waited)

    async def test_compiler_output_succeeds_exactly_at_the_limit(self):
        stdout = b'{"contracts":{}}'
        process = _FakeProcess(stdout)
        parser = LayoutParser(
            Settings(
                MAX_COMPILER_STDOUT_BYTES=len(stdout),
                MAX_COMPILER_STDERR_BYTES=0,
            )
        )
        with (
            patch(
                "app.services.layout.get_executable",
                return_value="/usr/bin/solc",
            ),
            patch(
                "app.services.layout.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
        ):
            output = await parser._run_solc_standard_json(
                "0.8.30",
                {"language": "Solidity"},
            )

        self.assertEqual(output, {"contracts": {}})
        self.assertFalse(process.killed)
        self.assertTrue(process.waited)


if __name__ == "__main__":
    unittest.main()
