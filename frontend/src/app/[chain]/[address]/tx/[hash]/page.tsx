'use client';

import { Container } from '@/components/layout/Container';
import { BackLink } from '@/components/layout/BackLink';
import { DiffTable } from '@/components/diff/DiffTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { EtherscanLink } from '@/components/ui/EtherscanLink';
import { truncateHash, truncateAddress } from '@/lib/utils';
import { getAddressExplorerUrl, getTxExplorerUrl, getBlockExplorerUrl } from '@/lib/constants';
import { useContract } from '@/lib/hooks/useContract';
import { useTxDiff } from '@/lib/hooks/useTxDiff';

interface TxDiffPageProps {
  params: { chain: string; address: string; hash: string };
}

export default function TxDiffPage({ params }: TxDiffPageProps) {
  const { chain, address, hash } = params;
  const { data: contract } = useContract(chain, address);
  const { data: diffData } = useTxDiff(chain, address, hash);

  const contractName = contract?.name;
  const abbreviatedAddress = truncateAddress(address);

  return (
    <Container>
      <BackLink href="/" />

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
              <span className="font-mono text-gray-900">{truncateHash(hash, 10)}</span>
              <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100">
                <CopyButton value={hash} />
                <EtherscanLink href={getTxExplorerUrl(chain, hash)} title="View transaction on Etherscan" />
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

        <DiffTable chainId={chain} address={address} txHash={hash} />
      </div>
    </Container>
  );
}
