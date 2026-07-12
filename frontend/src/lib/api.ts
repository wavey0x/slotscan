import type {
  ContractResponse,
  LayoutErrorResponse,
  SlotValueResponse,
  StorageLayoutResponse,
  StorageSnapshotResponse,
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

async function fetchWithTimeout(url: string, externalSignal?: AbortSignal): Promise<Response> {
  const timeoutController = new AbortController();
  const mergedController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), API_TIMEOUT_MS);

  // Merge external + timeout signals into mergedController
  const forwardAbort = (signal: AbortSignal) => {
    signal.addEventListener('abort', () => mergedController.abort(), { once: true });
  };
  forwardAbort(timeoutController.signal);
  if (externalSignal) forwardAbort(externalSignal);

  try {
    return await fetch(url, { signal: mergedController.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function fetchAPI<T>(url: string): Promise<T> {
  try {
    const res = await fetchWithTimeout(url);
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

export async function fetchContract(
  chainId: string,
  address: string
): Promise<ContractResponse> {
  return fetchAPI(`${API_BASE}/contracts/${chainId}/${address}`);
}

export async function fetchLayout(
  chainId: string,
  address: string
): Promise<StorageLayoutResponse> {
  return fetchAPI(`${API_BASE}/contracts/${chainId}/${address}/layout`);
}

export async function fetchStorage(
  chainId: string,
  address: string,
  block: number | 'latest',
  mappingKeys?: Record<number, string[]>
): Promise<StorageSnapshotResponse> {
  const params = new URLSearchParams();
  params.set('block', block.toString());
  if (mappingKeys) {
    params.set('mapping_keys', JSON.stringify(mappingKeys));
  }
  return fetchAPI(`${API_BASE}/storage/${chainId}/${address}?${params}`);
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

export async function fetchSlotValue(
  chainId: string,
  address: string,
  slot: string,
  block: number | 'latest'
): Promise<SlotValueResponse> {
  const params = new URLSearchParams();
  params.set('block', block.toString());
  return fetchAPI(`${API_BASE}/storage/${chainId}/${address}/slot/${slot}?${params}`);
}
