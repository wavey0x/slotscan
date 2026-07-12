'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getChainName } from '@/lib/constants';
import {
  clearRecentInspections,
  cn,
  getRecentInspections,
  RecentInspection,
  truncateAddress,
  truncateHash,
} from '@/lib/utils';

interface RecentSearchesProps {
  className?: string;
}

export function RecentSearches({ className }: RecentSearchesProps) {
  const [items, setItems] = useState<RecentInspection[]>([]);

  useEffect(() => {
    setItems(getRecentInspections());
  }, []);

  if (items.length === 0) return null;

  return (
    <section className={cn('w-full', className)}>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[10px] uppercase tracking-wide text-gray-500">Recent</h2>
        <button
          type="button"
          onClick={() => {
            clearRecentInspections();
            setItems([]);
          }}
          className="text-[10px] text-gray-500 hover:text-gray-900"
        >
          Clear
        </button>
      </div>
      <div className="border-y border-gray-300">
        {items.map((item) => (
          <Link
            key={`${item.kind}:${item.chain}:${item.value.toLowerCase()}`}
            href={item.kind === 'transaction' ? `/${item.chain}/tx/${item.value}` : `/${item.chain}/${item.value}`}
            className="flex items-center justify-between gap-4 border-b border-gray-200 px-2 py-2 text-xs no-underline last:border-b-0 hover:bg-gray-100 hover:no-underline"
          >
            <span className="min-w-0 truncate text-gray-900">
              {item.kind === 'contract' && item.name
                ? item.name
                : item.kind === 'contract'
                  ? truncateAddress(item.value)
                  : truncateHash(item.value, 10)}
            </span>
            <span className="shrink-0 text-[10px] text-gray-500">
              {item.kind === 'transaction' ? 'Transaction' : 'Contract'} · {getChainName(item.chain)}
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
