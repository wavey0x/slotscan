import { CopyButton } from '@/components/ui/CopyButton';
import { EntityKindBadge } from '@/components/ui/EntityKindBadge';
import { MetadataItem, MetricList } from '@/components/ui/Metadata';
import { getAddressExplorerUrl, getBlockExplorerUrl, getTxExplorerUrl } from '@/lib/constants';
import { TransactionStorageHistoryResponse } from '@/lib/types';
import { truncateAddress, truncateTxHash } from '@/lib/utils';

export function TransactionHeader({
  chain,
  data,
}: {
  chain: string;
  data: TransactionStorageHistoryResponse;
}) {
  const fromAddress = data.from_address;
  const toAddress = data.to_address || data.created_contract;

  return (
    <header className="mb-4 border-b border-gray-300 pb-4">
      <div className="max-w-5xl" data-testid="transaction-summary">
        <div className="mb-3 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <div className="flex min-w-0 items-center gap-0.5">
            <EntityKindBadge kind="txn" />
            <h1 className="min-w-0 truncate font-mono text-lg font-medium text-gray-900">
              <a
                href={getTxExplorerUrl(chain, data.tx_hash)}
                target="_blank"
                rel="noopener noreferrer"
                title={data.tx_hash}
              >
                {truncateTxHash(data.tx_hash)}
              </a>
            </h1>
            <CopyButton value={data.tx_hash} label="Copy transaction hash" />
          </div>
          {data.status === 'reverted' && (
            <span className="text-[10px] uppercase tracking-wide text-amber-600">
              Reverted
            </span>
          )}
        </div>

        <dl className="flex flex-wrap items-start gap-x-8 gap-y-2" data-testid="transaction-metadata">
          <MetadataItem label="Block">
            <a href={getBlockExplorerUrl(chain, data.block_number)} target="_blank" rel="noopener noreferrer">
              {data.block_number.toLocaleString()}
            </a>
          </MetadataItem>
          <MetadataItem label="From">
            {fromAddress ? (
              <span className="inline-flex items-center gap-0.5">
                <a href={getAddressExplorerUrl(chain, fromAddress)} target="_blank" rel="noopener noreferrer" title={fromAddress}>
                  {truncateAddress(fromAddress)}
                </a>
                <CopyButton value={fromAddress} label="Copy sender address" className="-my-1" />
              </span>
            ) : '—'}
          </MetadataItem>
          <MetadataItem label="To">
            {toAddress ? (
              <span className="inline-flex items-center gap-0.5">
                <a href={getAddressExplorerUrl(chain, toAddress)} target="_blank" rel="noopener noreferrer" title={toAddress}>
                  {truncateAddress(toAddress)}
                </a>
                <CopyButton
                  value={toAddress}
                  label={data.to_address ? 'Copy recipient address' : 'Copy created contract address'}
                  className="-my-1"
                />
              </span>
            ) : '—'}
          </MetadataItem>
        </dl>

        <MetricList
          className="mt-3 gap-x-5"
          metrics={[
            { label: 'Contracts', value: data.summary.storage_owners, testId: 'summary-contracts' },
            { label: 'Writes', value: data.summary.sstore_events, testId: 'summary-writes' },
            { label: 'Slots', value: data.summary.slots_written, testId: 'summary-slots' },
          ]}
        />
      </div>
    </header>
  );
}
