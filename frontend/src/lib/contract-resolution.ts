import type {
  ContractHistoryResponse,
  ContractResolutionStatus,
} from './types';

export function contractResolutionStatus(
  contract: ContractHistoryResponse,
): ContractResolutionStatus {
  if (contract.resolution_status) return contract.resolution_status;
  if (contract.errors.some((error) => error.toLowerCase().includes('timeout'))) {
    return 'timed_out';
  }
  if (contract.errors.length > 0 && !contract.name && !contract.layout_available) {
    return 'failed';
  }
  if (!contract.is_verified && !contract.name && !contract.layout_available) {
    return 'no_verified_source';
  }
  return 'resolved';
}

export function contractDisplayLabel(contract: ContractHistoryResponse): string {
  if (contract.name) return contract.name;
  const status = contractResolutionStatus(contract);
  if (status === 'not_resolved') return 'Resolution not completed';
  if (status === 'timed_out') return 'Resolution timed out';
  if (status === 'failed') return 'Resolution failed';
  if (contract.layout_available) return 'Unnamed contract';
  if (status === 'no_verified_source') return 'No verified source';
  return 'Verified source, no layout';
}

export function contractActivityStatus(
  contract: ContractHistoryResponse,
): string | null {
  const status = contractResolutionStatus(contract);
  if (status === 'timed_out' || status === 'failed' || status === 'not_resolved') {
    return contract.layout_available
      ? 'partial resolution'
      : 'partial resolution · raw slots';
  }
  if (!contract.layout_available) {
    return contract.is_verified || Boolean(contract.name)
      ? 'layout unavailable · raw slots'
      : 'raw slots';
  }
  if (!contract.name) return 'layout available';
  return null;
}

export function contractResolutionNotice(
  contract: ContractHistoryResponse,
): string | null {
  const status = contractResolutionStatus(contract);
  if (status === 'not_resolved') {
    return 'Contract resolution was not completed within this request. Raw slots are shown.';
  }
  if (status === 'timed_out') {
    return 'Contract resolution timed out. Retrying may recover names or variables.';
  }
  if (status === 'failed') {
    return 'Contract resolution failed temporarily. Retrying may recover names or variables.';
  }
  if (status === 'no_verified_source') {
    return 'No verified source or reusable storage layout was found. Raw slots are shown.';
  }
  if (!contract.layout_available && contract.is_verified) {
    return 'Verified source found, but no usable storage layout was produced. Raw slots are shown.';
  }
  if (!contract.name && contract.layout_available) {
    return 'Storage layout is available; the contract name is unavailable.';
  }
  return null;
}

export function hasRetryableContractResolution(
  contracts: ContractHistoryResponse[],
): boolean {
  return contracts.some((contract) => {
    const status = contractResolutionStatus(contract);
    return status === 'timed_out' || status === 'failed' || status === 'not_resolved';
  });
}
