const CHAIN_NAMES: Record<string, string> = {
  '1': 'Ethereum',
};

const CHAIN_EXPLORERS: Record<string, string> = {
  '1': 'https://etherscan.io',
};

export function getChainName(chainId: string | number): string {
  return CHAIN_NAMES[String(chainId)] || `Chain ${chainId}`;
}

function getExplorerUrl(chainId: string | number): string {
  return CHAIN_EXPLORERS[String(chainId)] || 'https://etherscan.io';
}

export function getAddressExplorerUrl(chainId: string | number, address: string): string {
  return `${getExplorerUrl(chainId)}/address/${address}`;
}

export function getTxExplorerUrl(chainId: string | number, txHash: string): string {
  return `${getExplorerUrl(chainId)}/tx/${txHash}`;
}

export function getBlockExplorerUrl(chainId: string | number, blockNumber: number): string {
  return `${getExplorerUrl(chainId)}/block/${blockNumber}`;
}
