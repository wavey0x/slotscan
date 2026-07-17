"""Custom exceptions for SlotScan."""


class SlotScanError(Exception):
    """Base exception for SlotScan."""

    pass


class NotAContractError(SlotScanError):
    """Raised when address has no bytecode."""

    def __init__(self, address: str):
        self.address = address
        super().__init__(f"No contract code at {address}")


class RPCError(SlotScanError):
    """Raised when RPC call fails."""

    def __init__(self, method: str, error: str):
        self.method = method
        self.error = error
        super().__init__(f"RPC {method} failed: {error}")


class VerificationProviderError(SlotScanError):
    """Raised when source verification providers fail inconclusively."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Verification providers unavailable: " + "; ".join(errors))


class CompilationError(SlotScanError):
    """Raised when solc compilation fails."""

    pass


class UnsupportedCompilerVersionError(SlotScanError):
    """Raised when compiler version doesn't support storage layout output."""

    def __init__(self, version: str, min_version: str = "0.5.13"):
        self.version = version
        self.min_version = min_version
        super().__init__(
            f"Storage layout not available for compiler version {version}. "
            f"This feature requires version {min_version} or later."
        )


class LayoutNotFoundError(SlotScanError):
    """Raised when contract not found in compiler output."""

    def __init__(self, contract_name: str):
        self.contract_name = contract_name
        super().__init__(f"Storage layout not found for {contract_name}")


class TransactionNotFoundError(SlotScanError):
    """Raised when transaction doesn't exist."""

    def __init__(self, tx_hash: str):
        self.tx_hash = tx_hash
        super().__init__(f"Transaction not found: {tx_hash}")


class TraceNotAvailableError(SlotScanError):
    """Raised when node doesn't support tracing."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Tracing not available: {reason}")
