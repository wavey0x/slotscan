"""Layout parser for extracting storage layouts from Solidity and Vyper source code."""

import asyncio
import hashlib
import json
import logging
import re
import resource
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import solcx
from solcx.install import get_executable

from app.config import Settings
from app.models.domain import (
    RawCompilerArtifact,
    StorageLayout,
    StorageType,
    StorageVariable,
)
from app.models.errors import CompilationError, LayoutNotFoundError, UnsupportedCompilerVersionError

# Minimum Solidity version that supports --storage-layout output
MIN_SOLC_VERSION_FOR_LAYOUT = (0, 5, 13)

# Minimum Vyper version that supports -f layout output
MIN_VYPER_VERSION_FOR_LAYOUT = (0, 3, 0)

logger = logging.getLogger(__name__)


def _limit_compiler_process(memory_limit_bytes: int, cpu_limit_seconds: int) -> None:
    """Apply hard resource limits in the compiler child process."""
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    except (OSError, ValueError):
        # RLIMIT_AS is not enforceable on every supported host (notably some
        # macOS configurations). Linux production workers still enforce it.
        pass
    try:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (cpu_limit_seconds, cpu_limit_seconds),
        )
    except (OSError, ValueError):
        pass


# Vyper type sizes in bytes
VYPER_TYPE_SIZES = {
    "address": 20,
    "bool": 1,
    "bytes32": 32,
    "bytes20": 20,
    "int128": 16,
    "int256": 32,
    "uint8": 1,
    "uint16": 2,
    "uint32": 4,
    "uint64": 8,
    "uint128": 16,
    "uint256": 32,
    "decimal": 32,  # Vyper decimal is 168-bit fixed point stored in 256 bits
}


class LayoutParser:
    """Parses Solidity source into storage layout."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self._compilation_semaphore = asyncio.Semaphore(
            self.settings.max_parallel_compilations
        )

    async def parse(
        self,
        contract_name: str,
        sources: dict[str, str],
        compiler_version: str,
        compiler_settings: Optional[dict] = None,
        metadata_settings: Optional[dict] = None,
        contract_fqname: Optional[str] = None,
    ) -> StorageLayout:
        """
        Compile sources and extract storage layout.

        Args:
            contract_name: Name of the target contract
            sources: Dict of filename -> source code
            compiler_version: Exact solc version e.g. "0.8.19"
            compiler_settings: Optimizer settings, etc.
            metadata_settings: Full metadata settings (from Sourcify/Etherscan) to improve fidelity

        Returns:
            Normalized StorageLayout
        """
        layout, _ = await self.parse_with_artifact(
            contract_name=contract_name,
            sources=sources,
            compiler_version=compiler_version,
            compiler_settings=compiler_settings,
            metadata_settings=metadata_settings,
            contract_fqname=contract_fqname,
        )
        return layout

    async def parse_with_artifact(
        self,
        contract_name: str,
        sources: dict[str, str],
        compiler_version: str,
        compiler_settings: Optional[dict] = None,
        metadata_settings: Optional[dict] = None,
        contract_fqname: Optional[str] = None,
    ) -> tuple[StorageLayout, RawCompilerArtifact]:
        solc_output, standard_input = await self._compile_with_layout(
            contract_name=contract_name,
            sources=sources,
            version=compiler_version,
            settings=compiler_settings,
            metadata_settings=metadata_settings,
        )

        raw_layout = self._extract_layout(contract_name, solc_output, contract_fqname)
        layout = self._normalize_layout(raw_layout, contract_name)
        artifact = self._make_artifact(
            language="Solidity",
            compiler_version=compiler_version,
            pipeline="solc-standard-json",
            standard_input=standard_input,
            compiler_output=solc_output,
            sources=sources,
        )
        return layout, artifact

    def parse_from_solc_output(
        self, contract_name: str, solc_output: dict, contract_fqname: Optional[str] = None
    ) -> StorageLayout:
        """Parse storage layout from existing solc output."""
        raw_layout = self._extract_layout(contract_name, solc_output, contract_fqname)
        return self._normalize_layout(raw_layout, contract_name)

    def parse_from_raw_layout(self, contract_name: str, raw_layout: dict) -> StorageLayout:
        """
        Parse storage layout from a raw solc storageLayout payload.

        This expects a dict with "storage" and "types" keys, as emitted by solc/Sourcify.
        """
        return self._normalize_layout(raw_layout, contract_name)

    async def _ensure_solc_version(self, version: str) -> str:
        """Ensure the required solc version is installed."""
        normalized = self._normalize_version(version)

        installed = await asyncio.to_thread(solcx.get_installed_solc_versions)
        installed_strs = [str(v) for v in installed]

        if normalized not in installed_strs:
            if not self.settings.allow_compiler_install:
                raise CompilationError(
                    f"solc {normalized} is not preinstalled and request-time installation is disabled"
                )
            if len(installed_strs) >= self.settings.max_installed_compilers:
                raise CompilationError(
                    "Compiler cache is at its configured version limit "
                    f"({self.settings.max_installed_compilers})"
                )
            try:
                logger.info(f"Installing solc {normalized}")
                async with self._compilation_semaphore:
                    await asyncio.wait_for(
                        asyncio.to_thread(solcx.install_solc, normalized),
                        timeout=self.settings.compiler_timeout_seconds,
                    )
            except Exception as e:
                raise CompilationError(f"Failed to install solc {normalized}: {e}")

        return normalized

    def _normalize_version(self, version: str) -> str:
        """
        Normalize compiler version string.

        Examples:
            "v0.8.19+commit.7dd6d404" -> "0.8.19"
            "0.8.19" -> "0.8.19"
        """
        # Remove 'v' prefix
        if version.startswith("v"):
            version = version[1:]

        # Remove commit hash
        if "+" in version:
            version = version.split("+")[0]

        # Validate format
        parts = version.split(".")
        if len(parts) < 2:
            raise CompilationError(f"Invalid compiler version: {version}")

        # Ensure we have at least 3 parts
        if len(parts) == 2:
            version = version + ".0"

        return version

    def _parse_version_tuple(self, version: str) -> tuple[int, int, int]:
        """Parse a normalized version string into a tuple for comparison."""
        parts = version.split(".")
        try:
            return (int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
        except (ValueError, IndexError):
            return (0, 0, 0)

    async def _compile_with_layout(
        self,
        contract_name: str,
        sources: dict[str, str],
        version: str,
        settings: Optional[dict],
        metadata_settings: Optional[dict] = None,
    ) -> tuple[dict, dict]:
        """Compile sources with storageLayout output enabled."""
        normalized_version = await self._ensure_solc_version(version)

        # Check if this Solidity version supports storage layout output
        version_tuple = self._parse_version_tuple(normalized_version)
        if version_tuple < MIN_SOLC_VERSION_FOR_LAYOUT:
            raise UnsupportedCompilerVersionError(normalized_version)

        standard_input = self.build_solidity_standard_input(
            sources,
            settings,
            metadata_settings,
        )

        try:
            async with self._compilation_semaphore:
                output = await self._run_solc_standard_json(
                    normalized_version,
                    standard_input,
                )
        except asyncio.TimeoutError as e:
            raise CompilationError("Solidity compilation timed out") from e
        except Exception as e:
            raise CompilationError(f"Compilation failed: {e}")

        # Check for errors
        if "errors" in output:
            errors = [e for e in output["errors"] if e.get("severity") == "error"]
            if errors:
                error_msgs = [e.get("message", str(e)) for e in errors]
                raise CompilationError(f"Compilation errors: {error_msgs}")

        return output, standard_input

    async def _run_solc_standard_json(
        self,
        version: str,
        standard_input: dict,
    ) -> dict:
        executable = get_executable(version)
        memory_limit = self.settings.compiler_memory_limit_mb * 1024 * 1024
        process = await asyncio.create_subprocess_exec(
            str(executable),
            "--standard-json",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=lambda: _limit_compiler_process(
                memory_limit,
                self.settings.compiler_timeout_seconds,
            ),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(
                    json.dumps(standard_input, separators=(",", ":")).encode("utf-8")
                ),
                timeout=self.settings.compiler_timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise CompilationError(
                "Solidity compiler process failed: "
                + stderr.decode("utf-8", errors="replace")[:4000]
            )
        try:
            output_start = stdout.index(b"{")
            return json.loads(stdout[output_start:])
        except (ValueError, json.JSONDecodeError) as exc:
            raise CompilationError("Solidity compiler returned invalid JSON") from exc

    def build_solidity_standard_input(
        self,
        sources: dict[str, str],
        settings: Optional[dict],
        metadata_settings: Optional[dict] = None,
    ) -> dict:
        """Build the canonical compiler input used for fingerprinting/compilation."""
        source_size = sum(len(content.encode("utf-8")) for content in sources.values())
        if source_size > self.settings.max_compilation_input_bytes:
            raise CompilationError(
                "Compiler input is "
                f"{source_size} bytes; limit is {self.settings.max_compilation_input_bytes}"
            )

        std_settings: dict = {
            "outputSelection": {
                "*": {
                    "*": ["storageLayout", "transientStorageLayout"],
                    "": ["ast"],
                }
            }
        }

        # Merge full metadata settings if available (more complete than partial settings)
        # Filter out keys that solc doesn't accept as input or may be malformed:
        # - outputSelection: we set our own
        # - compilationTarget: metadata-only, not an input setting
        # - libraries: Sourcify format may not match solc input format
        if metadata_settings:
            excluded_keys = {"outputSelection", "compilationTarget", "libraries"}
            std_settings.update({k: v for k, v in metadata_settings.items() if k not in excluded_keys})

        # Merge partial settings (optimizer/evmVersion/remappings)
        # Note: libraries are excluded due to format incompatibility with solc input
        if settings:
            if "optimizer" in settings:
                std_settings["optimizer"] = settings["optimizer"]
            if "evmVersion" in settings:
                std_settings["evmVersion"] = settings["evmVersion"]
            if "remappings" in settings:
                std_settings["remappings"] = settings["remappings"]

        standard_input = {
            "language": "Solidity",
            "sources": {
                filename: {"content": content} for filename, content in sources.items()
            },
            "settings": std_settings,
        }
        return standard_input

    def artifact_fingerprint(
        self,
        *,
        language: str,
        compiler_version: str,
        pipeline: str,
        standard_input: dict,
    ) -> str:
        fingerprint_input = {
            "language": language,
            "compiler_version": compiler_version,
            "pipeline": pipeline,
            "standard_input": standard_input,
        }
        return hashlib.sha256(
            json.dumps(
                fingerprint_input,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _make_artifact(
        self,
        *,
        language: str,
        compiler_version: str,
        pipeline: str,
        standard_input: dict,
        compiler_output: dict,
        sources: dict[str, str],
    ) -> RawCompilerArtifact:
        source_hashes = {
            filename: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for filename, content in sorted(sources.items())
        }
        fingerprint = self.artifact_fingerprint(
            language=language,
            compiler_version=compiler_version,
            pipeline=pipeline,
            standard_input=standard_input,
        )
        return RawCompilerArtifact(
            fingerprint=fingerprint,
            language=language,
            compiler_version=compiler_version,
            pipeline=pipeline,
            standard_input=standard_input,
            compiler_output=compiler_output,
            source_hashes=source_hashes,
        )

    def _extract_layout(self, contract_name: str, solc_output: dict, contract_fqname: Optional[str] = None) -> dict:
        """Find and extract storageLayout for target contract."""
        # If fully qualified name provided (path:Contract), use it
        if contract_fqname and ":" in contract_fqname:
            parts = contract_fqname.split(":")
            if len(parts) >= 2:
                filename = ":".join(parts[:-1])
                name = parts[-1]
                contracts = solc_output.get("contracts", {}).get(filename, {})
                if name in contracts and "storageLayout" in contracts[name]:
                    return contracts[name]["storageLayout"]

        # First pass: exact contract name match across files
        for filename, contracts in solc_output.get("contracts", {}).items():
            if contract_name in contracts and "storageLayout" in contracts[contract_name]:
                return contracts[contract_name]["storageLayout"]

        # Second pass: partial match
        for filename, contracts in solc_output.get("contracts", {}).items():
            for name, contract_output in contracts.items():
                if contract_name.lower() in name.lower() and "storageLayout" in contract_output:
                    return contract_output["storageLayout"]

        raise LayoutNotFoundError(contract_name)

    def _normalize_layout(self, raw_layout: dict, contract_name: str) -> StorageLayout:
        """Convert solc storageLayout output to our internal schema."""
        raw_types = raw_layout.get("types", {}) or {}
        types = self._parse_types(raw_types)
        variables = self._parse_variables(raw_layout.get("storage", []), types)

        # Get contract name from first variable's contract field if available
        if raw_layout.get("storage"):
            first_var = raw_layout["storage"][0]
            contract_field = first_var.get("contract", "")
            if ":" in contract_field:
                contract_name = contract_field.split(":")[-1]

        return StorageLayout(
            contract_name=contract_name,
            variables=variables,
            types=types,
        )

    def _parse_types(self, raw_types: dict) -> dict[str, StorageType]:
        """Parse type definitions from solc output."""
        types = {}

        for type_id, type_def in raw_types.items():
            encoding = type_def.get("encoding", "inplace")
            label = type_def.get("label", type_id)
            num_bytes_str = type_def.get("numberOfBytes", "0")
            num_bytes = int(num_bytes_str) if num_bytes_str else None

            kind = self._infer_kind(type_id, encoding)

            storage_type = StorageType(
                id=type_id,
                label=label,
                kind=kind,
                encoding=encoding,
                num_bytes=num_bytes,
                base_type=type_def.get("base"),
                element_type=None,
                array_length=None,
                key_type=None,
                value_type=None,
                members=None,
            )

            # Parse type-specific fields
            if encoding == "mapping":
                storage_type.key_type = type_def.get("key")
                storage_type.value_type = type_def.get("value")

            elif encoding == "dynamic_array":
                storage_type.element_type = type_def.get("base")

            elif "array" in type_id.lower():
                storage_type.element_type = type_def.get("base")
                storage_type.array_length = self._parse_array_length(type_id)

            elif "members" in type_def:
                storage_type.members = self._parse_struct_members(
                    type_def["members"], raw_types
                )

            types[type_id] = storage_type

        return types

    def _infer_kind(self, type_id: str, encoding: str) -> str:
        """Infer the kind of type from ID and encoding."""
        if encoding == "mapping":
            return "mapping"
        elif encoding == "dynamic_array":
            return "array"
        elif "array" in type_id.lower():
            return "array"
        elif type_id.startswith("t_struct"):
            return "struct"
        elif type_id.startswith("t_contract"):
            return "contract"
        else:
            return "value"

    def _parse_array_length(self, type_id: str) -> Optional[int]:
        """Extract array length from type ID like 't_array(t_uint256)10_storage'."""
        match = re.search(r"\)(\d+)_", type_id)
        if match:
            return int(match.group(1))
        return None

    def _parse_struct_members(
        self, raw_members: list[dict], all_types: dict
    ) -> list[StorageVariable]:
        """Parse struct member definitions into StorageVariables."""
        members = []
        for member in raw_members:
            member_type = member.get("type", "")
            type_info = all_types.get(member_type, {})
            num_bytes = int(type_info.get("numberOfBytes", 32))

            members.append(
                StorageVariable(
                    name=member.get("label", ""),
                    slot=int(member.get("slot", 0)),
                    offset=int(member.get("offset", 0)),
                    size=num_bytes,
                    type_id=member_type,
                    label=type_info.get("label", member_type),
                )
            )
        return members

    def _parse_variables(
        self, raw_storage: list[dict], types: dict[str, StorageType]
    ) -> list[StorageVariable]:
        """Parse storage variables from solc output."""
        variables = []

        for var in raw_storage:
            type_id = var.get("type", "")
            type_info = types.get(type_id)

            variables.append(
                StorageVariable(
                    name=var.get("label", ""),
                    slot=int(var.get("slot", 0)),
                    offset=int(var.get("offset", 0)),
                    size=(type_info.num_bytes or 32) if type_info else 32,
                    type_id=type_id,
                    label=type_info.label if type_info else type_id,
                )
            )

        return variables

    # --- Vyper Support ---

    async def parse_vyper(
        self,
        contract_name: str,
        sources: dict[str, str],
        compiler_version: str,
    ) -> StorageLayout:
        """
        Compile Vyper sources and extract storage layout.

        Args:
            contract_name: Name of the target contract
            sources: Dict of filename -> source code (should contain .vy files)
            compiler_version: Vyper version e.g. "0.3.10+commit.91361694"

        Returns:
            Normalized StorageLayout
        """
        layout, _ = await self.parse_vyper_with_artifact(
            contract_name,
            sources,
            compiler_version,
        )
        return layout

    async def parse_vyper_with_artifact(
        self,
        contract_name: str,
        sources: dict[str, str],
        compiler_version: str,
    ) -> tuple[StorageLayout, RawCompilerArtifact]:
        # Find the main .vy file (usually there's just one)
        vy_files = {k: v for k, v in sources.items() if k.endswith(".vy")}
        if not vy_files:
            raise CompilationError("No .vy files found in sources")

        # Use the first .vy file (or the one matching contract name)
        main_file = None
        main_content = None
        for filename, content in vy_files.items():
            if contract_name.lower() in filename.lower():
                main_file = filename
                main_content = content
                break
        if not main_file:
            main_file, main_content = next(iter(vy_files.items()))
        assert main_content is not None

        # Compile with Vyper
        raw_layout = await self._compile_vyper_with_layout(
            source_content=main_content,
            filename=main_file,
            version=compiler_version,
        )

        layout = self._normalize_vyper_layout(raw_layout, contract_name)
        standard_input = {
            "language": "Vyper",
            "sources": {
                filename: {"content": content}
                for filename, content in sources.items()
            },
            "settings": {"outputSelection": ["layout"]},
        }
        artifact = self._make_artifact(
            language="Vyper",
            compiler_version=compiler_version,
            pipeline="vvm-layout",
            standard_input=standard_input,
            compiler_output={"storageLayout": raw_layout},
            sources=sources,
        )
        return layout, artifact

    async def _compile_vyper_with_layout(
        self,
        source_content: str,
        filename: str,
        version: str,
    ) -> dict:
        """
        Compile Vyper source and get storage layout.

        Uses vvm (Vyper Version Manager) to ensure correct version is used.
        Falls back to system vyper if vvm is not available.
        """
        normalized_version = self._normalize_vyper_version(version)

        if len(source_content.encode("utf-8")) > self.settings.max_compilation_input_bytes:
            raise CompilationError(
                f"Compiler input exceeds {self.settings.max_compilation_input_bytes} bytes"
            )

        # Check if this Vyper version supports storage layout output
        version_tuple = self._parse_version_tuple(normalized_version)
        if version_tuple < MIN_VYPER_VERSION_FOR_LAYOUT:
            raise UnsupportedCompilerVersionError(
                normalized_version,
                min_version="0.3.0 (Vyper)"
            )

        # Try using vvm first (preferred - handles version management)
        try:
            import vvm
            logger.info("vvm imported, checking installed versions...")

            # Ensure version is installed
            installed = await asyncio.to_thread(vvm.get_installed_vyper_versions)
            installed_strs = [str(v) for v in installed]
            logger.info(f"vvm installed versions: {installed_strs[:5]}...")

            if normalized_version not in installed_strs:
                if not self.settings.allow_compiler_install:
                    raise CompilationError(
                        f"Vyper {normalized_version} is not preinstalled and request-time installation is disabled"
                    )
                if len(installed_strs) >= self.settings.max_installed_compilers:
                    raise CompilationError(
                        "Compiler cache is at its configured version limit "
                        f"({self.settings.max_installed_compilers})"
                    )
                logger.info(f"Installing Vyper {normalized_version} via vvm")
                async with self._compilation_semaphore:
                    await asyncio.wait_for(
                        asyncio.to_thread(vvm.install_vyper, normalized_version),
                        timeout=self.settings.compiler_timeout_seconds,
                    )

            from vvm.install import get_executable as get_vyper_executable

            logger.info(f"Compiling Vyper {normalized_version} layout for {filename} using vvm")
            async with self._compilation_semaphore:
                layout = await self._run_vyper_layout(
                    str(get_vyper_executable(normalized_version)),
                    source_content,
                )
            logger.info(f"vvm compilation returned type: {type(layout)}")

            # vvm returns the layout as a JSON string or dict
            if isinstance(layout, str):
                layout = json.loads(layout)

            # Handle both direct layout and wrapped format ({"storage_layout": {...}})
            if isinstance(layout, dict):
                if "storage_layout" in layout:
                    logger.info(f"Returning storage_layout with {len(layout['storage_layout'])} vars")
                    return layout["storage_layout"]
                logger.info(f"Returning layout directly with {len(layout)} vars")
                return layout

            raise CompilationError(f"Unexpected Vyper layout format: {type(layout)}")

        except ImportError as e:
            logger.warning(f"vvm import failed: {e}, falling back to system vyper")
        except CompilationError:
            raise
        except asyncio.TimeoutError as e:
            raise CompilationError("Vyper installation timed out") from e
        except Exception as e:
            logger.warning(f"vvm compilation failed: {type(e).__name__}: {e}, falling back to system vyper")
            import traceback
            logger.warning(f"vvm traceback: {traceback.format_exc()}")

        executable = shutil.which("vyper")
        if not executable:
            raise CompilationError(
                "Vyper compiler not found. Install with: pip install vyper vvm"
            )
        async with self._compilation_semaphore:
            return await self._run_vyper_layout(executable, source_content)

    async def _run_vyper_layout(
        self,
        executable: str,
        source_content: str,
    ) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "contract.vy"
            source_path.write_text(source_content)
            memory_limit = self.settings.compiler_memory_limit_mb * 1024 * 1024
            process = await asyncio.create_subprocess_exec(
                executable,
                "-f",
                "layout",
                str(source_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=lambda: _limit_compiler_process(
                    memory_limit,
                    self.settings.compiler_timeout_seconds,
                ),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.settings.compiler_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.wait()
                raise CompilationError("Vyper compilation timed out") from exc
            except asyncio.CancelledError:
                process.kill()
                await process.wait()
                raise
            if process.returncode != 0:
                raise CompilationError(
                    "Vyper compilation failed: "
                    + stderr.decode("utf-8", errors="replace")[:4000]
                )
            try:
                layout = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise CompilationError("Failed to parse Vyper layout output") from exc
            if "storage_layout" in layout:
                return layout["storage_layout"]
            return layout

    def _normalize_vyper_version(self, version: str) -> str:
        """
        Normalize Vyper version string.

        Examples:
            "vyper:0.2.4" -> "0.2.4"  (Etherscan format)
            "0.3.10+commit.91361694" -> "0.3.10"
            "v0.3.10" -> "0.3.10"
        """
        # Handle Etherscan format: "vyper:0.2.4"
        if version.lower().startswith("vyper:"):
            version = version.split(":", 1)[1]
        if version.startswith("v"):
            version = version[1:]
        if "+" in version:
            version = version.split("+")[0]
        return version

    def _normalize_vyper_layout(self, raw_layout: dict, contract_name: str) -> StorageLayout:
        """
        Convert Vyper storage layout output to our internal StorageLayout format.

        Vyper format:
            {"var_name": {"type": "...", "slot": N, "n_slots": M}, ...}

        Target format (StorageLayout):
            variables: [StorageVariable(name, slot, offset, size, type_id, label)]
            types: {type_id: StorageType(...)}
        """
        variables = []
        types = {}

        for var_name, var_info in raw_layout.items():
            type_str = var_info.get("type", "uint256")
            slot = var_info.get("slot", 0)
            n_slots = var_info.get("n_slots", 1)

            # Calculate size from type
            size = self._get_vyper_type_size(type_str, n_slots)

            variables.append(
                StorageVariable(
                    name=var_name,
                    slot=slot,
                    offset=0,  # Vyper doesn't pack variables within slots
                    size=size,
                    type_id=type_str,
                    label=type_str,
                )
            )

            # Build type entry if not already present
            if type_str not in types:
                types[type_str] = self._build_vyper_type(type_str, n_slots)

        # Sort variables by slot
        variables.sort(key=lambda v: v.slot)

        return StorageLayout(
            contract_name=contract_name,
            variables=variables,
            types=types,
        )

    def _get_vyper_type_size(self, type_str: str, n_slots: int) -> int:
        """Get the size in bytes for a Vyper type."""
        # For mappings and dynamic arrays, size is 32 (one slot for base)
        if type_str.startswith("HashMap[") or type_str.startswith("DynArray["):
            return 32

        # For static arrays, use n_slots
        if "[" in type_str and not type_str.startswith("HashMap") and not type_str.startswith("DynArray"):
            return n_slots * 32

        # Check known types
        if type_str in VYPER_TYPE_SIZES:
            return VYPER_TYPE_SIZES[type_str]

        # Default to 32 bytes (one slot)
        return 32

    def _build_vyper_type(self, type_str: str, n_slots: int) -> StorageType:
        """Build a StorageType for a Vyper type string."""
        # HashMap[key_type, value_type]
        if type_str.startswith("HashMap["):
            match = re.match(r'^HashMap\[(.+),\s*(.+)\]$', type_str)
            if match:
                return StorageType(
                    id=type_str,
                    label=type_str,
                    kind="mapping",
                    encoding="mapping",
                    key_type=match.group(1).strip(),
                    value_type=match.group(2).strip(),
                    num_bytes=32,
                )

        # DynArray[element_type, max_len]
        if type_str.startswith("DynArray["):
            match = re.match(r'^DynArray\[(.+),\s*(\d+)\]$', type_str)
            if match:
                return StorageType(
                    id=type_str,
                    label=type_str,
                    kind="array",
                    encoding="dynamic_array",
                    element_type=match.group(1).strip(),
                    array_length=int(match.group(2)),
                    num_bytes=32,
                )

        # Static array: type[length]
        if "[" in type_str:
            match = re.match(r'^(.+)\[(\d+)\]$', type_str)
            if match:
                return StorageType(
                    id=type_str,
                    label=type_str,
                    kind="array",
                    encoding="inplace",
                    element_type=match.group(1).strip(),
                    array_length=int(match.group(2)),
                    num_bytes=n_slots * 32,
                )

        # Primitive/value type
        size = VYPER_TYPE_SIZES.get(type_str, 32)
        return StorageType(
            id=type_str,
            label=type_str,
            kind="value",
            encoding="inplace",
            num_bytes=size,
        )
