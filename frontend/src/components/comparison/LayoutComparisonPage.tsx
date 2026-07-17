'use client';

import { useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  ComparisonForm,
  ComparisonUrlState,
  requestFromUrlState,
} from '@/components/comparison/ComparisonForm';
import { ComparisonResult } from '@/components/comparison/ComparisonResult';
import { useLayoutComparison } from '@/lib/hooks/useLayoutComparison';

function value(params: URLSearchParams, key: string): string {
  return params.get(key) || '';
}

export function LayoutComparisonPage({ chain }: { chain: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const submitted = useMemo<ComparisonUrlState>(() => ({
    from: value(searchParams, 'from'),
    to: value(searchParams, 'to'),
    fromBlock: value(searchParams, 'fromBlock'),
    fromBlockHash: value(searchParams, 'fromBlockHash'),
    toBlock: value(searchParams, 'toBlock'),
    toBlockHash: value(searchParams, 'toBlockHash'),
  }), [searchParams]);
  const request = useMemo(
    () => requestFromUrlState(submitted),
    [submitted],
  );
  const query = useLayoutComparison(chain, request);

  const submit = (next: ComparisonUrlState) => {
    const params = new URLSearchParams();
    params.set('from', next.from);
    params.set('to', next.to);
    if (next.fromBlock) params.set('fromBlock', next.fromBlock);
    if (next.fromBlockHash) params.set('fromBlockHash', next.fromBlockHash);
    if (next.toBlock) params.set('toBlock', next.toBlock);
    if (next.toBlockHash) params.set('toBlockHash', next.toBlockHash);
    router.push(`${pathname}?${params}`);
  };

  return (
    <div className="mx-auto w-full max-w-6xl">
      <header className="mb-6 border-b border-gray-300 pb-4">
        <h1 className="text-lg">Compare layouts</h1>
      </header>

      <ComparisonForm submitted={submitted} onSubmit={submit} />

      {query.isLoading && request && !query.data && (
        <div className="mt-8 border border-gray-300 p-5 text-sm text-gray-500">
          Resolving exact layouts…
        </div>
      )}
      {query.error && !query.data && (
        <div className="mt-8 border border-red/30 p-5">
          <div className="text-sm text-red">Comparison request failed</div>
          <p className="mt-1 text-xs text-gray-500">
            {(query.error as Error).message}
          </p>
          <button
            type="button"
            onClick={() => { void query.refetch(); }}
            className="mt-3 text-xs text-gray-900 underline underline-offset-2"
          >
            Retry
          </button>
        </div>
      )}
      {query.data && (
        <ComparisonResult
          chain={chain}
          report={query.data}
          refreshing={query.isFetching}
          refreshFailed={Boolean(query.error)}
          onRetry={() => { void query.refetch(); }}
        />
      )}
    </div>
  );
}
