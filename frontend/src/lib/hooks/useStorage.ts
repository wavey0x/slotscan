'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchStorage } from '../api';

export function useStorage(
  chainId: string,
  address: string,
  block?: number,
  mappingKeys?: Record<number, string[]>
) {
  return useQuery({
    queryKey: ['storage', chainId, address, block, mappingKeys],
    queryFn: () => fetchStorage(chainId, address, block!, mappingKeys),
    staleTime: 60 * 1000,
    enabled: !!chainId && !!address && block !== undefined,
  });
}
