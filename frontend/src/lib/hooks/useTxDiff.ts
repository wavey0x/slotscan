'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchTxDiff } from '../api';

export function useTxDiff(chainId: string, address: string, txHash: string) {
  return useQuery({
    queryKey: ['txDiff', chainId, address, txHash],
    queryFn: () => fetchTxDiff(chainId, address, txHash),
    staleTime: Infinity, // Transaction data is immutable
    gcTime: Infinity, // Keep cached forever
    enabled: !!chainId && !!address && !!txHash,
    retry: false, // fail fast so UI can show an error instead of hanging
  });
}
