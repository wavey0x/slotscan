"""Layout parser for extracting storage layouts from Solidity source code."""

import logging
import re
from typing import Optional

import solcx

from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.models.errors import CompilationError, LayoutNotFoundError

logger = logging.getLogger(__name__)


class LayoutParser:
    """Parses Solidity source into storage layout."""

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
        solc_output = await self._compile_with_layout(
            contract_name=contract_name,
            sources=sources,
            version=compiler_version,
            settings=compiler_settings,
            metadata_settings=metadata_settings,
        )

        raw_layout = self._extract_layout(contract_name, solc_output, contract_fqname)
        return self._normalize_layout(raw_layout, contract_name)

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

        installed = solcx.get_installed_solc_versions()
        installed_strs = [str(v) for v in installed]

        if normalized not in installed_strs:
            try:
                logger.info(f"Installing solc {normalized}")
                solcx.install_solc(normalized)
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

    async def _compile_with_layout(
        self,
        contract_name: str,
        sources: dict[str, str],
        version: str,
        settings: Optional[dict],
        metadata_settings: Optional[dict] = None,
    ) -> dict:
        """Compile sources with storageLayout output enabled."""
        normalized_version = await self._ensure_solc_version(version)

        # Build standard JSON input
        std_settings: dict = {"outputSelection": {"*": {"*": ["storageLayout"]}}}

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

        try:
            solcx.set_solc_version(normalized_version)
            output = solcx.compile_standard(standard_input)
        except Exception as e:
            raise CompilationError(f"Compilation failed: {e}")

        # Check for errors
        if "errors" in output:
            errors = [e for e in output["errors"] if e.get("severity") == "error"]
            if errors:
                error_msgs = [e.get("message", str(e)) for e in errors]
                raise CompilationError(f"Compilation errors: {error_msgs}")

        return output

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
                    size=type_info.num_bytes if type_info else 32,
                    type_id=type_id,
                    label=type_info.label if type_info else type_id,
                )
            )

        return variables
