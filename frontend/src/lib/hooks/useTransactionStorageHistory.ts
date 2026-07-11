'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchTransactionStorageHistory } from '../api';

export function useTransactionStorageHistory(chainId: string, txHash: string) {
  return useQuery({
    queryKey: ['transactionStorageHistory', chainId, txHash],
    queryFn: () => fetchTransactionStorageHistory(chainId, txHash, true),
    staleTime: Infinity,
    gcTime: Infinity,
    enabled: !!chainId && !!txHash,
    retry: false,
  });
}
