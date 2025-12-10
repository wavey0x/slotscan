'use client';

import { useSearchParams, useRouter } from 'next/navigation';
import { useState, useEffect } from 'react';
import { Container } from '@/components/layout/Container';
import { ContractNav, TabType } from '@/components/layout/ContractNav';
import { LayoutTable } from '@/components/layout/LayoutTable';
import { DiffTable } from '@/components/diff/DiffTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { EtherscanLink } from '@/components/ui/EtherscanLink';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { Loading } from '@/components/ui/Loading';
import { truncateHash, truncateAddress, updateRecentSearchName, getRecentTransactions, saveRecentTransaction, updateRecentTransactionBlock } from '@/lib/utils';
import { getTxExplorerUrl, getBlockExplorerUrl, getAddressExplorerUrl } from '@/lib/constants';
import { useLayout } from '@/lib/hooks/useLayout';
import { useContract } from '@/lib/hooks/useContract';
import { useTxDiff } from '@/lib/hooks/useTxDiff';
import { APIError } from '@/lib/api';

interface ContractPageProps {
  params: { chain: string; address: string };
}

// Layout view component
function LayoutView({
  chain,
  address,
  contractName,
}: {
  chain: string;
  address: string;
  contractName?: string | null;
}) {
  const { data: layout, isLoading, error } = useLayout(chain, address);

  if (isLoading) {
    return (
      <Loading
        messages={[
          'Fetching contract',
          'Loading storage layout',
          'Parsing variable types',
        ]}
      />
    );
  }

  if (error) {
    const apiError = error instanceof APIError ? error : null;
    const errorCode = apiError?.code;
    const details = apiError?.details as Record<string, string> | undefined;

    // Handle proxy contracts
    if (errorCode === 'PROXY_IMPL_NOT_VERIFIED' && details?.implementation_address) {
      const proxyTypeDisplay: Record<string, string> = {
        'eip1167': 'EIP-1167 Minimal Proxy',
        'eip1967': 'EIP-1967 Transparent Proxy',
        'eip1822': 'EIP-1822 UUPS Proxy',
      };
      const proxyLabel = proxyTypeDisplay[details.proxy_type || ''] || 'Proxy';

      return (
        <div className="p-6 border border-gray-300">
          <div className="flex items-center gap-2 mb-3">
            <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 rounded">
              {proxyLabel}
            </span>
          </div>
          <div className="text-gray-900 mb-2">Implementation not verified</div>
          <p className="text-sm text-gray-500 mb-3">
            This contract delegates to an implementation that is not verified on Sourcify or Etherscan.
          </p>
          <div className="text-sm">
            <span className="text-gray-500">Implementation: </span>
            <a
              href={getAddressExplorerUrl(chain, details.implementation_address)}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-blue-600 hover:underline"
            >
              {truncateAddress(details.implementation_address)}
            </a>
          </div>
        </div>
      );
    }

    // Handle unverified contracts
    if (errorCode === 'NOT_VERIFIED') {
      return (
        <div className="p-6 border border-gray-300">
          <div className="text-gray-900 mb-2">Contract not verified</div>
          <p className="text-sm text-gray-500">
            Source code is not available on Sourcify or Etherscan.
          </p>
        </div>
      );
    }

    // Handle other errors
    return (
      <div className="p-6 border border-gray-300">
        <div className="text-gray-900 mb-2">Storage layout not available</div>
        <p className="text-sm text-gray-500">
          {apiError?.message || 'Contract may not be verified or source code is unavailable.'}
        </p>
      </div>
    );
  }

  if (!layout) {
    return (
      <div className="p-6 border border-gray-300 text-gray-500">
        No storage layout available
      </div>
    );
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-lg font-medium text-gray-900">Storage Layout</h1>
      </div>
      <LayoutTable chainId={chain} address={address} layout={layout} />
    </>
  );
}

// Transaction input prompt
function TransactionPrompt({
  chain,
  address,
  onSubmit,
}: {
  chain: string;
  address: string;
  onSubmit: (txHash: string) => void;
}) {
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [recentTx, setRecentTx] = useState<{ txHash: string; blockNumber?: number; timestamp: number }[]>([]);

  // Load recent transactions on mount
  useEffect(() => {
    setRecentTx(getRecentTransactions(chain, address));
  }, [chain, address]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const value = input.trim();

    if (!value) {
      setError('Please enter a transaction hash');
      return;
    }

    if (!/^0x[a-fA-F0-9]{64}$/.test(value)) {
      setError('Invalid transaction hash format');
      return;
    }

    saveRecentTransaction(chain, address, value);
    onSubmit(value);
  };

  const handleRecentClick = (txHash: string) => {
    saveRecentTransaction(chain, address, txHash);
    onSubmit(txHash);
  };

  return (
    <div className="max-w-lg">
      <h2 className="text-lg font-medium text-gray-900 mb-4">Analyze Transaction</h2>
      <p className="text-sm text-gray-500 mb-4">
        Enter a transaction hash to analyze storage changes made by that transaction.
      </p>

      <form onSubmit={handleSubmit} className="space-y-3">
        <Input
          type="text"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setError(null);
          }}
          placeholder="Transaction hash (0x...)"
          className="w-full font-mono text-sm"
        />
        {error && <p className="text-red text-xs">{error}</p>}
        <Button type="submit" variant="secondary" className="w-full">
          Analyze
        </Button>
      </form>

      {/* Recent transactions */}
      {recentTx.length > 0 && (
        <div className="mt-8">
          <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">
            Recent
          </div>
          <div className="border border-gray-300 divide-y divide-gray-300">
            {recentTx.map((tx) => (
              <button
                key={tx.txHash}
                onClick={() => handleRecentClick(tx.txHash)}
                className="w-full text-left px-3 py-2 hover:bg-gray-100 transition-colors"
              >
                <div className="font-mono text-sm text-gray-900">
                  {truncateHash(tx.txHash, 12)}
                </div>
                {tx.blockNumber && (
                  <div className="text-xs text-gray-500">
                    Block {tx.blockNumber.toLocaleString()}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Transaction diff view
function TransactionDiffView({
  chain,
  address,
  txHash,
}: {
  chain: string;
  address: string;
  txHash: string;
}) {
  const { data: diffData } = useTxDiff(chain, address, txHash);

  // Update recent transaction with block number when loaded
  useEffect(() => {
    if (diffData?.block_number) {
      updateRecentTransactionBlock(chain, address, txHash, diffData.block_number);
    }
  }, [chain, address, txHash, diffData?.block_number]);

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-medium text-gray-900">State Changes</h1>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm mb-6">
        {/* Txn Hash */}
        <dt className="text-gray-500">Txn Hash:</dt>
        <dd>
          <span className="group inline-flex items-center gap-2 -ml-2 px-2 py-0.5 transition border border-transparent hover:border-dashed hover:border-gray-400">
            <span className="font-mono text-gray-900">{truncateHash(txHash, 10)}</span>
            <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100">
              <CopyButton value={txHash} />
              <EtherscanLink href={getTxExplorerUrl(chain, txHash)} title="View transaction on Etherscan" />
            </span>
          </span>
        </dd>

        {/* Block */}
        {diffData && (
          <>
            <dt className="text-gray-500">Block:</dt>
            <dd>
              <span className="group inline-flex items-center gap-2 -ml-2 px-2 py-0.5 transition border border-transparent hover:border-dashed hover:border-gray-400">
                <span className="font-mono text-gray-900">{diffData.block_number.toLocaleString()}</span>
                <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100">
                  <CopyButton value={String(diffData.block_number)} />
                  <EtherscanLink href={getBlockExplorerUrl(chain, diffData.block_number)} title="View block on Etherscan" />
                </span>
              </span>
            </dd>
          </>
        )}

        {/* Slots */}
        {diffData && (
          <>
            <dt className="text-gray-500">Slots:</dt>
            <dd className="font-mono text-gray-900 py-0.5">{diffData.slots.length} modified</dd>
          </>
        )}
      </dl>

      <DiffTable chainId={chain} address={address} txHash={txHash} />
    </>
  );
}

export default function ContractPage({ params }: ContractPageProps) {
  const { chain, address } = params;
  const router = useRouter();
  const searchParams = useSearchParams();
  const txHash = searchParams.get('tx');

  // Determine initial tab based on URL
  const [activeTab, setActiveTab] = useState<TabType>(txHash ? 'transaction' : 'layout');

  // Sync tab with URL when txHash changes
  useEffect(() => {
    if (txHash) {
      setActiveTab('transaction');
    }
  }, [txHash]);

  // Fetch contract for name
  const { data: contract } = useContract(chain, address);
  const { data: layout } = useLayout(chain, address);
  const contractName = contract?.name || layout?.contract_name;

  // Update recent search with contract name when loaded
  useEffect(() => {
    if (contractName) {
      updateRecentSearchName(chain, address, contractName);
    }
  }, [chain, address, contractName]);

  // Handle tab change
  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
    // If switching to layout, clear the tx param from URL
    if (tab === 'layout' && txHash) {
      router.replace(`/${chain}/${address}`);
    }
  };

  // Handle transaction submit from prompt
  const handleTxSubmit = (hash: string) => {
    router.push(`/${chain}/${address}?tx=${hash}`);
  };

  return (
    <Container>
      <ContractNav
        chain={chain}
        address={address}
        contractName={contractName}
        activeTab={activeTab}
        onTabChange={handleTabChange}
      />

      {activeTab === 'layout' && (
        <LayoutView chain={chain} address={address} contractName={contractName} />
      )}

      {activeTab === 'transaction' && !txHash && (
        <TransactionPrompt chain={chain} address={address} onSubmit={handleTxSubmit} />
      )}

      {activeTab === 'transaction' && txHash && (
        <TransactionDiffView chain={chain} address={address} txHash={txHash} />
      )}
    </Container>
  );
}
