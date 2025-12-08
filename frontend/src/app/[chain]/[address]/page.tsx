'use client';

import { useSearchParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Container } from '@/components/layout/Container';
import { BackLink } from '@/components/layout/BackLink';
import { DiffTable } from '@/components/diff/DiffTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { EtherscanLink } from '@/components/ui/EtherscanLink';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { truncateHash, truncateAddress } from '@/lib/utils';
import { getAddressExplorerUrl, getTxExplorerUrl, getBlockExplorerUrl } from '@/lib/constants';
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
  const abbreviatedAddress = truncateAddress(address);

  return (
    <Container>
      <BackLink href={`/${chain}/${address}`} label="Back to contract" />

      <div className="mt-6">
        <h1 className="text-xl font-medium text-gray-900 mb-4">State Changes</h1>

        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm mb-6">
          {/* Contract */}
          <dt className="text-gray-500">Contract:</dt>
          <dd>
            <span className="group inline-flex items-center gap-2 -ml-2 px-2 py-0.5 rounded-md transition border border-transparent hover:border-dashed hover:border-gray-400">
              <span className="font-mono text-gray-900">
                {contractName ? `${contractName} (${abbreviatedAddress})` : abbreviatedAddress}
              </span>
              <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100">
                <CopyButton value={address} />
                <EtherscanLink href={getAddressExplorerUrl(chain, address)} />
              </span>
            </span>
          </dd>

          {/* Txn Hash */}
          <dt className="text-gray-500">Txn Hash:</dt>
          <dd>
            <span className="group inline-flex items-center gap-2 -ml-2 px-2 py-0.5 rounded-md transition border border-transparent hover:border-dashed hover:border-gray-400">
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
                <span className="group inline-flex items-center gap-2 -ml-2 px-2 py-0.5 rounded-md transition border border-transparent hover:border-dashed hover:border-gray-400">
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
      </div>
    </Container>
  );
}

// Prompt view when no tx hash provided
function PromptView({ chain, address }: { chain: string; address: string }) {
  const router = useRouter();
  const { data: contract } = useContract(chain, address);
  const contractName = contract?.name;
  const abbreviatedAddress = truncateAddress(address);

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
      <BackLink href="/" />

      <div className="mt-6 mb-8">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-gray-500">Contract:</dt>
          <dd>
            <span className="group inline-flex items-center gap-2 -ml-2 px-2 py-0.5 rounded-md transition border border-transparent hover:border-dashed hover:border-gray-400">
              <span className="font-mono text-gray-900">
                {contractName ? `${contractName} (${abbreviatedAddress})` : abbreviatedAddress}
              </span>
              <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100">
                <CopyButton value={address} />
                <EtherscanLink href={getAddressExplorerUrl(chain, address)} />
              </span>
            </span>
          </dd>
        </dl>
      </div>

      <div className="max-w-md">
        <h2 className="text-lg font-medium text-gray-400 mb-4">View Storage Changes</h2>

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
            View Storage Changes
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
