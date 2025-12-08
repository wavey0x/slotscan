"""Custom exceptions for StorageScan."""


class StorageScanError(Exception):
    """Base exception for StorageScan."""

    pass


class NotAContractError(StorageScanError):
    """Raised when address has no bytecode."""

    def __init__(self, address: str):
        self.address = address
        super().__init__(f"No contract code at {address}")


class RPCError(StorageScanError):
    """Raised when RPC call fails."""

    def __init__(self, method: str, error: str):
        self.method = method
        self.error = error
        super().__init__(f"RPC {method} failed: {error}")


class CompilationError(StorageScanError):
    """Raised when solc compilation fails."""

    pass


class LayoutNotFoundError(StorageScanError):
    """Raised when contract not found in compiler output."""

    def __init__(self, contract_name: str):
        self.contract_name = contract_name
        super().__init__(f"Storage layout not found for {contract_name}")


class TransactionNotFoundError(StorageScanError):
    """Raised when transaction doesn't exist."""

    def __init__(self, tx_hash: str):
        self.tx_hash = tx_hash
        super().__init__(f"Transaction not found: {tx_hash}")


class TraceNotAvailableError(StorageScanError):
    """Raised when node doesn't support tracing."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Tracing not available: {reason}")


class DecodeError(StorageScanError):
    """Raised when decoding fails."""

    def __init__(self, type_label: str, reason: str):
        self.type_label = type_label
        self.reason = reason
        super().__init__(f"Failed to decode {type_label}: {reason}")


class SlotLimitExceeded(StorageScanError):
    """Raised when too many slots requested."""

    def __init__(self, requested: int, limit: int):
        self.requested = requested
        self.limit = limit
        super().__init__(f"Requested {requested} slots, limit is {limit}")
