'use client';

import { useSearchParams, useRouter } from 'next/navigation';
import { useState, useEffect } from 'react';
import { Container } from '@/components/layout/Container';
import { ContractNav } from '@/components/layout/ContractNav';
import { DiffTable } from '@/components/diff/DiffTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { EtherscanLink } from '@/components/ui/EtherscanLink';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { truncateHash, updateRecentSearchName } from '@/lib/utils';
import { getTxExplorerUrl, getBlockExplorerUrl } from '@/lib/constants';
import { useContract } from '@/lib/hooks/useContract';
import { useTxDiff } from '@/lib/hooks/useTxDiff';

interface ContractPageProps {
  params: { chain: string; address: string };
}

// Separate component for tx diff view to use hooks properly
function TxDiffView({ chain, address, txHash }: { chain: string; address: string; txHash: string }) {
  const { data: contract } = useContract(chain, address);
  const { data: diffData } = useTxDiff(chain, address, txHash);
  const contractName = contract?.name;

  // Update recent search with contract name when loaded
  useEffect(() => {
    if (contractName) {
      updateRecentSearchName(chain, address, contractName);
    }
  }, [chain, address, contractName]);

  return (
    <Container>
      <ContractNav chain={chain} address={address} contractName={contractName} />

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
    </Container>
  );
}

// Prompt view when no tx hash provided
function PromptView({ chain, address }: { chain: string; address: string }) {
  const router = useRouter();
  const { data: contract } = useContract(chain, address);
  const contractName = contract?.name;

  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);

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
    router.push(`/${chain}/${address}?tx=${value}`);
  };

  return (
    <Container>
      <ContractNav chain={chain} address={address} contractName={contractName} />

      <div className="max-w-md">
        <h2 className="text-lg font-medium text-gray-900 mb-4">View Storage Changes</h2>
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
          <Button type="submit" variant="primary" className="w-full">
            Analyze Transaction
          </Button>
        </form>
      </div>
    </Container>
  );
}

export default function ContractPage({ params }: ContractPageProps) {
  const { chain, address } = params;
  const searchParams = useSearchParams();
  const txHash = searchParams.get('tx');

  // If tx hash provided, show transaction diff view
  if (txHash) {
    return <TxDiffView chain={chain} address={address} txHash={txHash} />;
  }

  // Otherwise prompt for tx hash
  return <PromptView chain={chain} address={address} />;
}
