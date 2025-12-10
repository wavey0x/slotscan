'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchStorage } from '../api';

export function useStorage(
  chainId: string,
  address: string,
  block: number | 'latest' = 'latest',
  mappingKeys?: Record<number, string[]>
) {
  return useQuery({
    queryKey: ['storage', chainId, address, block, mappingKeys],
    queryFn: () => fetchStorage(chainId, address, block, mappingKeys),
    staleTime: Infinity, // Never auto-refetch - user must click refresh
    gcTime: 5 * 60 * 1000, // Keep in cache for 5 minutes
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
    enabled: !!chainId && !!address,
  });
}
