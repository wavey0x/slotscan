'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getRecentSearches, RecentSearch, truncateAddress, truncateHash, clearRecentSearches } from '@/lib/utils';
import { getChainName } from '@/lib/constants';

interface RecentSearchesProps {
  className?: string;
}

export function RecentSearches({ className }: RecentSearchesProps) {
  const [searches, setSearches] = useState<RecentSearch[]>([]);

  useEffect(() => {
    setSearches(getRecentSearches());
  }, []);

  if (searches.length === 0) return null;

  const handleClear = () => {
    clearRecentSearches();
    setSearches([]);
  };

  return (
    <div className={className}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-gray-500 uppercase tracking-wide">Recent</span>
        <button
          onClick={handleClear}
          className="text-xs text-gray-500 hover:text-gray-900"
        >
          Clear
        </button>
      </div>
      <div className="border border-gray-300 divide-y divide-gray-300">
        {searches.map((search, i) => {
          let href = `/${search.chain}/${search.address}`;
          if (search.blockOrTx) {
            const param = search.blockOrTx.startsWith('0x') ? 'tx' : 'block';
            href += `?${param}=${search.blockOrTx}`;
          }

          return (
            <Link
              key={i}
              href={href}
              className="block px-3 py-2 hover:bg-gray-100 no-underline hover:no-underline"
            >
              <div className="text-sm text-gray-900">
                {truncateAddress(search.address)}
              </div>
              <div className="text-xs text-gray-500">
                {getChainName(search.chain)}
                {search.blockOrTx && ` · ${search.blockOrTx.startsWith('0x') ? `TX ${truncateHash(search.blockOrTx)}` : `Block ${search.blockOrTx}`}`}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
