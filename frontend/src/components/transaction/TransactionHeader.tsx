import { CopyButton } from '@/components/ui/CopyButton';
import { MetadataGrid, MetadataItem, MetricList } from '@/components/ui/Metadata';
import { getAddressExplorerUrl, getBlockExplorerUrl, getTxExplorerUrl } from '@/lib/constants';
import { TransactionStorageHistoryResponse } from '@/lib/types';
import { cn, truncateAddress, truncateHash } from '@/lib/utils';

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
    <header className="mb-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-medium text-gray-900">Transaction storage history</h1>
        <span className={cn(
          'text-[10px] uppercase tracking-wide',
          data.status === 'success' ? 'text-gray-500' : 'text-amber-600'
        )}>
          {data.status}
        </span>
      </div>

      <MetadataGrid>
        <MetadataItem label="Transaction">
          <span className="flex min-w-0 items-center gap-0.5">
            <a
              href={getTxExplorerUrl(chain, data.tx_hash)}
              target="_blank"
              rel="noopener noreferrer"
              className="truncate"
              title={data.tx_hash}
            >
              {truncateHash(data.tx_hash, 10)}
            </a>
            <CopyButton value={data.tx_hash} label="Copy transaction hash" />
          </span>
        </MetadataItem>
        <MetadataItem label="Block">
          <a href={getBlockExplorerUrl(chain, data.block_number)} target="_blank" rel="noopener noreferrer">
            {data.block_number.toLocaleString()}
          </a>
        </MetadataItem>
        <MetadataItem label="From">
          {fromAddress ? (
            <a href={getAddressExplorerUrl(chain, fromAddress)} target="_blank" rel="noopener noreferrer" title={fromAddress}>
              {truncateAddress(fromAddress)}
            </a>
          ) : '—'}
        </MetadataItem>
        <MetadataItem label="To">
          {toAddress ? (
            <a href={getAddressExplorerUrl(chain, toAddress)} target="_blank" rel="noopener noreferrer" title={toAddress}>
              {truncateAddress(toAddress)}
            </a>
          ) : '—'}
        </MetadataItem>
      </MetadataGrid>

      <MetricList
        className="mt-3"
        metrics={[
          { label: 'Contracts', value: data.summary.storage_owners, testId: 'summary-contracts' },
          { label: 'Writes', value: data.summary.sstore_events, testId: 'summary-writes' },
          { label: 'Slots', value: data.summary.slots_written, testId: 'summary-slots' },
        ]}
      />
    </header>
  );
}
