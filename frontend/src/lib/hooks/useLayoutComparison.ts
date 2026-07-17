'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { fetchLayoutComparison } from '@/lib/api';
import type { LayoutComparisonRequest } from '@/lib/types';

export function useLayoutComparison(
  chainId: string,
  request: LayoutComparisonRequest | null,
) {
  return useQuery({
    queryKey: [
      'layout-comparison',
      chainId,
      request?.fromAddress,
      request?.toAddress,
      request?.fromBlock,
      request?.fromBlockHash,
      request?.toBlock,
      request?.toBlockHash,
    ],
    queryFn: () => fetchLayoutComparison(chainId, request!),
    enabled: Boolean(request),
    placeholderData: request ? keepPreviousData : undefined,
    retry: false,
  });
}
