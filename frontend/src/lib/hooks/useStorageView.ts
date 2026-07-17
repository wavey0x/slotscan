'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { fetchStorageView } from '../api';

export function useStorageView(
  chainId: string,
  address: string,
  selector: string = 'latest'
) {
  return useQuery({
    queryKey: ['storage-view', chainId, address, selector],
    queryFn: () => fetchStorageView(chainId, address, selector),
    placeholderData: keepPreviousData,
    staleTime: 0,
    refetchOnMount: true,
    refetchOnReconnect: true,
    refetchOnWindowFocus: true,
    enabled: Boolean(chainId && address),
  });
}
