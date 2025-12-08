'use client';

import { useSearchParams } from 'next/navigation';
import { useState, useEffect } from 'react';
import { Container } from '@/components/layout/Container';
import { BackLink } from '@/components/layout/BackLink';
import { ContractHeader } from '@/components/contract/ContractHeader';
import { StorageTree } from '@/components/storage/StorageTree';
import { BlockSelector } from '@/components/storage/BlockSelector';
import { DiffTable } from '@/components/diff/DiffTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { EtherscanLink } from '@/components/ui/EtherscanLink';
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

export default function ContractPage({ params }: ContractPageProps) {
  const { chain, address } = params;
  const searchParams = useSearchParams();
  const txHash = searchParams.get('tx');
  const blockParam = searchParams.get('block');

  const [blockNumber, setBlockNumber] = useState<number | undefined>(
    blockParam ? parseInt(blockParam) : undefined
  );
  const [latestBlock, setLatestBlock] = useState<number | undefined>();

  // Fetch latest block if no block specified
  useEffect(() => {
    if (!blockNumber && !txHash) {
      fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'}/contracts/${chain}/${address}`)
        .then((res) => res.json())
        .then(() => {
          // Use a recent block (we'd need to fetch this from the API)
          // For now, set a placeholder that will be updated by storage fetch
          setLatestBlock(undefined);
        })
        .catch(() => {});
    }
  }, [chain, address, blockNumber, txHash]);

  // If tx hash provided, show transaction diff view
  if (txHash) {
    return (
      <TxDiffView chain={chain} address={address} txHash={txHash} />
    );
  }

  // Show storage at block
  const displayBlock = blockNumber || latestBlock;

  return (
    <Container>
      <BackLink href="/" />
      <ContractHeader chainId={chain} address={address} />

      <div className="mt-8">
        <div className="flex items-center justify-between mb-4">
          <span className="text-xs text-gray-500 uppercase tracking-wide">Storage</span>
          <BlockSelector
            currentBlock={displayBlock}
            onBlockChange={setBlockNumber}
          />
        </div>

        {displayBlock ? (
          <StorageTree
            chainId={chain}
            address={address}
            blockNumber={displayBlock}
          />
        ) : (
          <div className="text-gray-500 p-8 text-center border border-gray-300">
            Enter a block number to view storage
          </div>
        )}
      </div>
    </Container>
  );
}
