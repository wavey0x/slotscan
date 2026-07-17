import type {
  StorageQueryRequest,
  StorageQueryResponse,
  StorageViewResponse,
  TransactionStorageHistoryResponse,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/slotscan';

const API_TIMEOUT_MS = 120000; // 120s hard timeout to fail gracefully in UI

// Custom error class that preserves API error details
export class APIError extends Error {
  code: string;
  details?: Record<string, unknown>;

  constructor(message: string, code: string, details?: Record<string, unknown>) {
    super(message);
    this.name = 'APIError';
    this.code = code;
    this.details = details;
  }
}

async function fetchWithTimeout(url: string, init?: RequestInit): Promise<Response> {
  const timeoutController = new AbortController();
  const mergedController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), API_TIMEOUT_MS);

  // Merge external + timeout signals into mergedController
  const forwardAbort = (signal: AbortSignal) => {
    signal.addEventListener('abort', () => mergedController.abort(), { once: true });
  };
  forwardAbort(timeoutController.signal);
  if (init?.signal) forwardAbort(init.signal);

  try {
    return await fetch(url, { ...init, signal: mergedController.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function fetchAPI<T>(url: string, init?: RequestInit): Promise<T> {
  try {
    const res = await fetchWithTimeout(url, init);
    if (!res.ok) {
      const body = await res.json().catch(() => ({ error: 'Request failed', code: 'UNKNOWN' }));
      // FastAPI wraps error details in { detail: {...} }
      const error = body.detail || body;
      throw new APIError(
        error.error || error.message || 'Request failed',
        error.code || 'UNKNOWN',
        error
      );
    }
    return res.json();
  } catch (err: unknown) {
    if (err instanceof APIError) {
      throw err;
    }
    const isAbort = (err as Error)?.name === 'AbortError';
    if (isAbort) {
      throw new APIError('Request timed out', 'TIMEOUT');
    }
    throw err;
  }
}

export async function fetchStorageView(
  chainId: string,
  address: string,
  selector: string = 'latest'
): Promise<StorageViewResponse> {
  const params = new URLSearchParams();
  params.set('block', selector);
  return fetchAPI(`${API_BASE}/contracts/${chainId}/${address}/storage-view?${params}`);
}

export async function queryStorage(
  request: StorageQueryRequest
): Promise<StorageQueryResponse> {
  return fetchAPI(`${API_BASE}/storage/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}

export async function fetchTransactionStorageHistory(
  chainId: string,
  txHash: string,
  includeGlobalOrder = true
): Promise<TransactionStorageHistoryResponse> {
  const params = new URLSearchParams();
  params.set('include_global_order', String(includeGlobalOrder));
  return fetchAPI(`${API_BASE}/tx/${chainId}/${txHash}?${params}`);
}
