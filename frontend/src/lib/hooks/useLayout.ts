'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchLayout } from '../api';

export function useLayout(chainId: string, address: string) {
  return useQuery({
    queryKey: ['layout', chainId, address],
    queryFn: () => fetchLayout(chainId, address),
    staleTime: 5 * 60 * 1000,
    enabled: !!chainId && !!address,
  });
}
