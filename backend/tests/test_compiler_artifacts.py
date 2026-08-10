import asyncio
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.models.errors import CompilationError
from app.services.namespace_storage import (
    ERC7201_HARNESS_CONTRACT,
    ERC7201_HARNESS_SOURCE,
)
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


class _MemoryArtifactRepository:
    def __init__(self):
        self.rows = {}
        self.save_count = 0

    async def get(self, fingerprint):
        return self.rows.get(fingerprint)

    async def save(self, artifact):
        self.rows[artifact.fingerprint] = artifact
        self.save_count += 1


def _solidity_output():
    return {
        "contracts": {
            "C.sol": {
                "C": {
                    "storageLayout": {
                        "storage": [
                            {
                                "label": "value",
                                "slot": "0",
                                "offset": 0,
                                "type": "t_uint256",
                                "contract": "C.sol:C",
                            }
                        ],
                        "types": {
                            "t_uint256": {
                                "encoding": "inplace",
                                "label": "uint256",
                                "numberOfBytes": "32",
                            }
                        },
                    }
                }
            }
        }
    }


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
            [
                "storageLayout",
                "transientStorageLayout",
                "metadata",
                "evm.deployedBytecode.object",
                "evm.deployedBytecode.immutableReferences",
                "evm.deployedBytecode.linkReferences",
            ],
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


class CompilerArtifactCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_solidity_requests_compile_once_then_hit_cache(self):
        parser = LayoutParser()
        repo = _MemoryArtifactRepository()
        sources = {"C.sol": "contract C { uint256 value; }"}
        standard_input = parser.build_solidity_standard_input(sources, None)

        async def compile_once(**_kwargs):
            await asyncio.sleep(0.01)
            return _solidity_output(), standard_input

        parser._compile_with_layout = AsyncMock(side_effect=compile_once)
        calls = [
            parser.parse_with_artifact(
                "C",
                sources,
                "0.8.30",
                compiler_artifact_repo=repo,
            )
            for _ in range(3)
        ]

        results = await asyncio.gather(*calls)
        cached_layout, cached_artifact = await parser.parse_with_artifact(
            "C",
            sources,
            "0.8.30",
            compiler_artifact_repo=repo,
        )

        self.assertEqual(parser._compile_with_layout.await_count, 1)
        self.assertEqual(repo.save_count, 1)
        self.assertEqual(parser._artifact_locks, {})
        self.assertEqual(
            [layout.to_dict() for layout, _artifact in results],
            [cached_layout.to_dict()] * 3,
        )
        self.assertTrue(
            all(
                artifact.fingerprint == cached_artifact.fingerprint
                for _layout, artifact in results
            )
        )

    async def test_invalid_cached_artifact_is_recompiled_and_replaced(self):
        parser = LayoutParser()
        repo = _MemoryArtifactRepository()
        sources = {"C.sol": "contract C { uint256 value; }"}
        standard_input = parser.build_solidity_standard_input(sources, None)
        valid = parser._make_artifact(
            language="Solidity",
            compiler_version="0.8.30",
            pipeline="solc-standard-json",
            standard_input=standard_input,
            compiler_output=_solidity_output(),
            sources=sources,
        )
        repo.rows[valid.fingerprint] = replace(valid, compiler_output={})
        parser._compile_with_layout = AsyncMock(
            return_value=(_solidity_output(), standard_input)
        )

        layout, artifact = await parser.parse_with_artifact(
            "C",
            sources,
            "0.8.30",
            compiler_artifact_repo=repo,
        )

        self.assertEqual(layout.variables[0].name, "value")
        self.assertEqual(parser._compile_with_layout.await_count, 1)
        self.assertEqual(repo.save_count, 1)
        self.assertEqual(repo.rows[artifact.fingerprint].compiler_output, _solidity_output())

    async def test_failed_compilation_is_not_cached_and_releases_lock(self):
        parser = LayoutParser()
        repo = _MemoryArtifactRepository()
        parser._compile_with_layout = AsyncMock(
            side_effect=CompilationError("compiler failed")
        )

        for _ in range(2):
            with self.assertRaisesRegex(CompilationError, "compiler failed"):
                await parser.parse_with_artifact(
                    "C",
                    {"C.sol": "contract C {}"},
                    "0.8.30",
                    compiler_artifact_repo=repo,
                )

        self.assertEqual(parser._compile_with_layout.await_count, 2)
        self.assertEqual(repo.rows, {})
        self.assertEqual(repo.save_count, 0)
        self.assertEqual(parser._artifact_locks, {})

    async def test_vyper_entry_source_is_part_of_cache_identity(self):
        parser = LayoutParser()
        repo = _MemoryArtifactRepository()
        sources = {
            "A.vy": "# @version 0.3.10\na: public(uint256)\n",
            "B.vy": "# @version 0.3.10\nb: public(uint256)\n",
        }

        async def compile_target(*, entry_source, **_kwargs):
            name = entry_source.removesuffix(".vy").lower()
            return (
                {name: {"type": "uint256", "slot": 0}},
                "0x5f5ffd",
            )

        parser._compile_vyper_with_layout = AsyncMock(side_effect=compile_target)
        first_layout, first_artifact = await parser.parse_vyper_with_artifact(
            "A",
            sources,
            "0.3.10",
            entry_source="A.vy",
            compiler_artifact_repo=repo,
        )
        second_layout, second_artifact = await parser.parse_vyper_with_artifact(
            "B",
            sources,
            "0.3.10",
            entry_source="B.vy",
            compiler_artifact_repo=repo,
        )
        await parser.parse_vyper_with_artifact(
            "A",
            sources,
            "0.3.10",
            entry_source="A.vy",
            compiler_artifact_repo=repo,
        )

        self.assertEqual(first_layout.variables[0].name, "a")
        self.assertEqual(second_layout.variables[0].name, "b")
        self.assertNotEqual(first_artifact.fingerprint, second_artifact.fingerprint)
        self.assertEqual(parser._compile_vyper_with_layout.await_count, 2)
        self.assertEqual(repo.save_count, 2)

    async def test_erc7201_harness_compilation_is_cached(self):
        parser = LayoutParser()
        repo = _MemoryArtifactRepository()
        sources = {"C.sol": "contract C {}"}
        harness_source = "contract SlotScanERC7201Harness { uint256 value; }"
        augmented_sources = {
            **sources,
            ERC7201_HARNESS_SOURCE: harness_source,
        }
        standard_input = parser.build_solidity_standard_input(
            augmented_sources,
            None,
            None,
        )
        compiler_output = {
            "contracts": {
                ERC7201_HARNESS_SOURCE: {
                    ERC7201_HARNESS_CONTRACT: {
                        "storageLayout": {
                            "storage": [
                                {
                                    "label": "value",
                                    "slot": "0",
                                    "offset": 0,
                                    "type": "t_uint256",
                                }
                            ],
                            "types": {
                                "t_uint256": {
                                    "encoding": "inplace",
                                    "label": "uint256",
                                    "numberOfBytes": "32",
                                }
                            },
                        }
                    }
                }
            }
        }
        parser._compile_with_layout = AsyncMock(
            return_value=(compiler_output, standard_input)
        )

        first, _ = await parser.compile_exact_namespace_types(
            sources=sources,
            compiler_version="0.8.30",
            compiler_settings=None,
            harness_source=harness_source,
            compiler_artifact_repo=repo,
        )
        second, _ = await parser.compile_exact_namespace_types(
            sources=sources,
            compiler_version="0.8.30",
            compiler_settings=None,
            harness_source=harness_source,
            compiler_artifact_repo=repo,
        )

        self.assertEqual(first, second)
        self.assertEqual(parser._compile_with_layout.await_count, 1)
        self.assertEqual(repo.save_count, 1)


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

    async def test_vyper_artifact_retains_layout_and_runtime_from_one_compile(self):
        parser = LayoutParser()
        parser._compile_vyper_with_layout = AsyncMock(
            return_value=(
                {
                    "value": {
                        "type": "uint256",
                        "slot": 0,
                    }
                },
                "0x5f5ffd",
            )
        )

        layout, artifact = await parser.parse_vyper_with_artifact(
            "Vault",
            {
                "Vault.vy": (
                    "# @version 0.3.10\nvalue: public(uint256)\n"
                )
            },
            "0.3.10",
            entry_source="Vault.vy",
        )

        self.assertEqual(layout.variables[0].name, "value")
        self.assertEqual(layout.variables[0].slot, 0)
        self.assertEqual(
            artifact.compiler_output["bytecodeRuntime"],
            "0x5f5ffd",
        )
        self.assertEqual(
            artifact.standard_input["settings"]["outputSelection"],
            ["layout", "bytecode_runtime"],
        )

    async def test_vyper_runner_stages_complete_source_tree(self):
        parser = LayoutParser()
        stdout = (
            json.dumps(
                {
                    "storage_layout": {
                        "balanceOf": {
                            "type": "HashMap[address, uint256]",
                            "slot": 7,
                            "n_slots": 1,
                        }
                    }
                }
            ).encode()
            + b"\n0x5f5ffd\n"
        )
        process = _FakeProcess(stdout)
        sources = {
            "src/Vault.vy": "from . import token\ninitializes: token\n",
            "src/token.vy": "balanceOf: HashMap[address, uint256]\n",
            "src/IERC20.vyi": "interface IERC20:\n    pass\n",
        }

        async def create_process(*args, **_kwargs):
            root = Path(args[args.index("-p") + 1])
            entry = Path(args[-1])
            self.assertEqual(entry, root / "src/Vault.vy")
            self.assertEqual(
                (root / "src/token.vy").read_text(encoding="utf-8"),
                sources["src/token.vy"],
            )
            self.assertEqual(
                (root / "src/IERC20.vyi").read_text(encoding="utf-8"),
                sources["src/IERC20.vyi"],
            )
            return process

        with patch(
            "app.services.layout.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=create_process),
        ):
            layout, runtime = await parser._run_vyper_outputs(
                "/usr/bin/vyper",
                sources,
                "src/Vault.vy",
            )

        self.assertEqual(layout["balanceOf"]["slot"], 7)
        self.assertEqual(runtime, "0x5f5ffd")

    async def test_vyper_runner_rejects_source_path_escape(self):
        parser = LayoutParser()

        with self.assertRaisesRegex(CompilationError, "Invalid Vyper source path"):
            await parser._run_vyper_outputs(
                "/usr/bin/vyper",
                {"../Vault.vy": "value: uint256\n"},
                "../Vault.vy",
            )

    async def test_vyper_04_compiler_layout_is_not_replaced_by_source_inference(self):
        parser = LayoutParser()
        parser._compile_vyper_with_layout = AsyncMock(
            return_value=(
                {
                    "allowance": {
                        "type": "HashMap[address, HashMap[address, uint256]]",
                        "slot": 12,
                        "n_slots": 1,
                    },
                    "totalSupply": {
                        "type": "uint256",
                        "slot": 14,
                        "n_slots": 1,
                    },
                },
                "0x5f5ffd",
            )
        )

        layout, _ = await parser.parse_vyper_with_artifact(
            "Vault",
            {
                "src/Vault.vy": (
                    "# pragma version 0.4.3\n"
                    "allowance: reentrant(HashMap[address, HashMap[address, uint256]])\n"
                    "totalSupply: reentrant(uint256)\n"
                ),
                "src/token.vy": "moduleValue: uint256\n",
            },
            "vyper:0.4.3",
            entry_source="src/Vault.vy",
        )

        self.assertEqual(
            [(variable.name, variable.slot) for variable in layout.variables],
            [("allowance", 12), ("totalSupply", 14)],
        )
        allowance = layout.get_type(layout.variables[0].type_id)
        self.assertEqual(allowance.key_type, "address")
        self.assertEqual(
            allowance.value_type,
            "HashMap[address, uint256]",
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
