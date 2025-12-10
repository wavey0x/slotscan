'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchLayout } from '../api';

export function useLayout(chainId: string, address: string) {
  return useQuery({
    queryKey: ['layout', chainId, address],
    queryFn: () => fetchLayout(chainId, address),
    staleTime: Infinity, // Layout is immutable for a contract
    gcTime: Infinity, // Keep cached forever
    enabled: !!chainId && !!address,
  });
}
