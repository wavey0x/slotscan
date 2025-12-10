'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchContract } from '../api';

export function useContract(chainId: string, address: string) {
  return useQuery({
    queryKey: ['contract', chainId, address],
    queryFn: () => fetchContract(chainId, address),
    staleTime: Infinity, // Contract metadata is immutable
    gcTime: Infinity, // Keep cached forever
    enabled: !!chainId && !!address,
  });
}
