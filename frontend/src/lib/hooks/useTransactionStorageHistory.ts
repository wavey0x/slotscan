'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { APIError, fetchTransactionStorageHistory } from '../api';
import { hasRetryableContractResolution } from '../contract-resolution';

const AUTO_RETRY_DELAY_MS = 750;
const NETWORK_RETRY_DELAY_MS = 1000;

export function useTransactionStorageHistory(chainId: string, txHash: string) {
  const queryKey = `${chainId}:${txHash.toLowerCase()}`;
  const scheduledRetry = useRef<string | null>(null);
  const [finishedRetry, setFinishedRetry] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ['transactionStorageHistory', chainId, txHash],
    queryFn: () => fetchTransactionStorageHistory(chainId, txHash, true),
    staleTime: (currentQuery) => {
      const data = currentQuery.state.data;
      return data && hasRetryableContractResolution(data.contracts) ? 0 : Infinity;
    },
    gcTime: Infinity,
    enabled: !!chainId && !!txHash,
    retry: (failureCount, error) => (
      error instanceof APIError
      && error.code === 'NETWORK_ERROR'
      && failureCount < 1
    ),
    retryDelay: NETWORK_RETRY_DELAY_MS,
  });

  useEffect(() => {
    if (
      !query.data
      || !hasRetryableContractResolution(query.data.contracts)
      || scheduledRetry.current === queryKey
    ) {
      return;
    }
    scheduledRetry.current = queryKey;
    const timer = window.setTimeout(() => {
      void query.refetch().finally(() => {
        if (scheduledRetry.current === queryKey) {
          setFinishedRetry(queryKey);
        }
      });
    }, AUTO_RETRY_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [query.data, query.refetch, queryKey]);

  return {
    ...query,
    resolutionAutoRetryFinished: finishedRetry === queryKey,
  };
}
