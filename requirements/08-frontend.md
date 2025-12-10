# Frontend Application

## Overview

The Frontend is a Next.js 14+ application providing the user interface for SlotScan. It features a minimalist design focused on displaying storage layouts and transaction diffs clearly. MVP focus: desktop-first, deep links, layout tree, tx diff table, raw/decoded toggle, and clear degraded states (hex-only, trace unavailable). Charts/exports are out of scope.

## Implementation Status: ✅ Complete

### Key Implementation Decisions

1. **CSS Grid for Alignment**: State Changes page uses CSS Grid (`grid-cols-[auto_1fr]`) for perfect label/value alignment even with hover elements.

2. **Copyable Value Pattern**: Addresses, tx hashes, and block numbers use dotted border hover pattern (`border border-transparent hover:border-dashed hover:border-gray-400`) to indicate interactivity.

3. **Etherscan Links**: `EtherscanLink` component provides outbound links with chain-aware explorer URLs.

4. **Contract Display Format**: When contract name is available, displays as `ContractName (0x12AB...5678)` with abbreviated address.

5. **React Query for Data Fetching**: All API calls use React Query hooks with appropriate stale times (infinite for tx data, 5 min for contracts).

## Location

```
frontend/
├── src/
│   ├── app/                    # Next.js App Router pages
│   ├── components/             # React components
│   ├── lib/                    # Utilities and API client
│   └── styles/                 # Global styles
├── public/                     # Static assets
└── package.json
```

## Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| `next` | 14.x | React framework |
| `react` | 18.x | UI library |
| `tailwindcss` | 3.x | Styling |
| `@tanstack/react-query` | 5.x | Server state management |
| `@radix-ui/react-*` | latest | Accessible UI primitives |
| `lucide-react` | latest | Icons |

## MVP Scope & Degraded States
- Desktop-first; deep links for chain/address/block/tx.
- Core views only: search, layout tree, tx diff table, raw/decoded toggle.
- Unverified contracts: hex-only with optional heuristic hints.
- Tracing unavailable: show warning/empty state instead of failing.
- Charts/exports and mobile polish are out of scope for v1.
- Readability: show mapping base slot and computed slot hashes with truncated display + tooltip, decode mapping values using value type, and prefer concise labels over raw hashes.

## Project Structure

```
frontend/src/
├── app/
│   ├── layout.tsx              # Root layout
│   ├── page.tsx                # Home page (search)
│   ├── globals.css             # Global styles
│   └── [chain]/
│       └── [address]/
│           ├── page.tsx        # Contract page
│           └── tx/
│               └── [hash]/
│                   └── page.tsx # Transaction diff page
├── components/
│   ├── ui/                     # Base UI components
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Select.tsx
│   │   ├── Card.tsx
│   │   ├── Badge.tsx
│   │   ├── Skeleton.tsx
│   │   └── Tooltip.tsx
│   ├── layout/
│   │   ├── Header.tsx
│   │   ├── Container.tsx
│   │   └── BackLink.tsx
│   ├── search/
│   │   ├── SearchForm.tsx
│   │   └── RecentSearches.tsx
│   ├── contract/
│   │   ├── ContractHeader.tsx
│   │   ├── ProxyBadge.tsx
│   │   └── VerificationBadge.tsx
│   ├── storage/
│   │   ├── StorageTree.tsx
│   │   ├── TreeNode.tsx
│   │   ├── SlotValue.tsx
│   │   ├── ValueDisplay.tsx
│   │   ├── MappingKeyInput.tsx
│   │   └── BlockSelector.tsx
│   └── diff/
│       ├── DiffTable.tsx
│       ├── DiffRow.tsx
│       └── ValueChange.tsx
├── lib/
│   ├── api.ts                  # API client
│   ├── types.ts                # TypeScript types
│   ├── utils.ts                # Utilities
│   ├── constants.ts            # Chain configs, etc.
│   └── hooks/
│       ├── useContract.ts
│       ├── useStorage.ts
│       └── useTxDiff.ts
└── styles/
    └── globals.css
```

## Pages

### Home Page (Search)

```tsx
// src/app/page.tsx

export default function HomePage() {
  return (
    <Container>
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <h1 className="text-3xl font-light mb-8">SlotScan</h1>
        <SearchForm />
        <RecentSearches className="mt-12" />
      </div>
    </Container>
  );
}
```

### Contract Page

```tsx
// src/app/[chain]/[address]/page.tsx

interface ContractPageProps {
  params: { chain: string; address: string };
  searchParams: { block?: string; tx?: string };
}

export default function ContractPage({ params, searchParams }: ContractPageProps) {
  const { chain, address } = params;
  const { block, tx } = searchParams;

  // If tx provided, show transaction diff view
  // Otherwise show storage at block (default: latest)

  return (
    <Container>
      <BackLink href="/" />
      <ContractHeader chainId={chain} address={address} />

      {tx ? (
        <TransactionDiffView
          chainId={chain}
          address={address}
          txHash={tx}
        />
      ) : (
        <StorageLayoutView
          chainId={chain}
          address={address}
          blockNumber={block ? parseInt(block) : undefined}
        />
      )}
    </Container>
  );
}
```

### Transaction Diff Page (Alternative Route)

```tsx
// src/app/[chain]/[address]/tx/[hash]/page.tsx

export default function TxDiffPage({ params }) {
  const { chain, address, hash } = params;

  return (
    <Container>
      <BackLink href={`/${chain}/${address}`} />
      <ContractHeader chainId={chain} address={address} />
      <TransactionDiffView
        chainId={chain}
        address={address}
        txHash={hash}
      />
    </Container>
  );
}
```

## Components

### SearchForm

```tsx
// src/components/search/SearchForm.tsx

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Button } from '@/components/ui/Button';
import { CHAINS } from '@/lib/constants';
import { isAddress, isTxHash } from '@/lib/utils';

export function SearchForm() {
  const router = useRouter();
  const [chain, setChain] = useState('1');
  const [address, setAddress] = useState('');
  const [blockOrTx, setBlockOrTx] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Validate address
    if (!isAddress(address)) {
      setError('Invalid contract address');
      return;
    }

    // Build URL
    let url = `/${chain}/${address}`;

    if (blockOrTx) {
      if (isTxHash(blockOrTx)) {
        url += `?tx=${blockOrTx}`;
      } else if (/^\d+$/.test(blockOrTx)) {
        url += `?block=${blockOrTx}`;
      } else {
        setError('Enter a valid block number or transaction hash');
        return;
      }
    }

    // Save to recent searches
    saveRecentSearch({ chain, address, blockOrTx });

    router.push(url);
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-xl space-y-4">
      <div className="flex gap-2">
        <Select
          value={chain}
          onChange={setChain}
          options={CHAINS}
          className="w-40"
        />
        <Input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="Contract Address"
          className="flex-1 font-mono"
        />
      </div>

      <Input
        value={blockOrTx}
        onChange={(e) => setBlockOrTx(e.target.value)}
        placeholder="Block number or Transaction hash (optional)"
        className="font-mono"
      />

      {error && (
        <p className="text-red-500 text-sm">{error}</p>
      )}

      <Button type="submit" className="w-full">
        Analyze
      </Button>
    </form>
  );
}
```

### StorageTree

```tsx
// src/components/storage/StorageTree.tsx

'use client';

import { useState } from 'react';
import { TreeNode } from './TreeNode';
import { useStorage } from '@/lib/hooks/useStorage';
import { Skeleton } from '@/components/ui/Skeleton';

interface StorageTreeProps {
  chainId: string;
  address: string;
  blockNumber?: number;
}

export function StorageTree({ chainId, address, blockNumber }: StorageTreeProps) {
  const { data, isLoading, error } = useStorage(chainId, address, blockNumber);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  const toggleNode = (path: string) => {
    setExpandedNodes(prev => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  if (isLoading) {
    return <StorageTreeSkeleton />;
  }

  if (error) {
    return (
      <div className="text-red-500 p-4">
        Failed to load storage: {error.message}
      </div>
    );
  }

  if (!data?.is_verified) {
    return <RawSlotView slots={data?.slots || []} />;
  }

  return (
    <div className="font-mono text-sm">
      {data.slots.map((slot, index) => (
        <TreeNode
          key={slot.slot}
          slot={slot}
          depth={0}
          isExpanded={expandedNodes.has(slot.variable_path || slot.slot)}
          onToggle={() => toggleNode(slot.variable_path || slot.slot)}
        />
      ))}
    </div>
  );
}

function StorageTreeSkeleton() {
  return (
    <div className="space-y-2">
      {[...Array(8)].map((_, i) => (
        <Skeleton key={i} className="h-6 w-full" style={{ marginLeft: (i % 3) * 24 }} />
      ))}
    </div>
  );
}
```

### TreeNode

```tsx
// src/components/storage/TreeNode.tsx

import { ChevronRight, ChevronDown } from 'lucide-react';
import { SlotValue } from './SlotValue';
import { ValueDisplay } from './ValueDisplay';
import { cn } from '@/lib/utils';

interface TreeNodeProps {
  slot: SlotData;
  depth: number;
  isExpanded: boolean;
  onToggle: () => void;
}

export function TreeNode({ slot, depth, isExpanded, onToggle }: TreeNodeProps) {
  const hasChildren = slot.type_label?.includes('struct') ||
                      slot.type_label?.includes('mapping') ||
                      slot.type_label?.includes('array');

  return (
    <div className={cn("border-l border-gray-200", depth > 0 && "ml-6")}>
      <div
        className={cn(
          "flex items-center gap-2 py-1 px-2 hover:bg-gray-50 cursor-pointer",
          "transition-colors"
        )}
        onClick={onToggle}
      >
        {/* Expand/collapse icon */}
        {hasChildren ? (
          isExpanded ? (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-400" />
          )
        ) : (
          <span className="w-4" /> // Spacer
        )}

        {/* Node bullet */}
        <span className="w-2 h-2 rounded-full bg-gray-400" />

        {/* Variable name and type */}
        <span className="font-medium text-gray-900">
          {slot.variable_name || `Slot ${slot.slot}`}
        </span>
        {slot.type_label && (
          <span className="text-gray-500">
            ({slot.type_label})
          </span>
        )}

        {/* Slot info */}
        <span className="text-gray-400 text-xs">
          Slot {parseInt(slot.slot, 16)}
        </span>
      </div>

      {/* Value */}
      <div className="ml-10 pl-2 py-1 text-gray-600">
        <ValueDisplay
          value={slot.display_value || slot.raw_value}
          rawValue={slot.raw_value}
          typeLabel={slot.type_label}
        />
      </div>

      {/* Children (for structs, mappings) */}
      {isExpanded && slot.children && (
        <div className="ml-4">
          {slot.children.map((child, i) => (
            <TreeNode
              key={i}
              slot={child}
              depth={depth + 1}
              isExpanded={false}
              onToggle={() => {}}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

### DiffTable

```tsx
// src/components/diff/DiffTable.tsx

'use client';

import { useState } from 'react';
import { useTxDiff } from '@/lib/hooks/useTxDiff';
import { DiffRow } from './DiffRow';
import { Toggle } from '@/components/ui/Toggle';
import { Skeleton } from '@/components/ui/Skeleton';

interface DiffTableProps {
  chainId: string;
  address: string;
  txHash: string;
}

export function DiffTable({ chainId, address, txHash }: DiffTableProps) {
  const { data, isLoading, error } = useTxDiff(chainId, address, txHash);
  const [showHex, setShowHex] = useState(false);

  if (isLoading) {
    return <DiffTableSkeleton />;
  }

  if (error) {
    return (
      <div className="text-red-500 p-4">
        Failed to load transaction: {error.message}
      </div>
    );
  }

  if (!data?.changes.length) {
    return (
      <div className="text-gray-500 p-8 text-center">
        No storage changes in this transaction
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-gray-500">
          {data.changes.length} slot{data.changes.length !== 1 ? 's' : ''} modified
        </div>
        <Toggle
          label="Show HEX"
          checked={showHex}
          onChange={setShowHex}
        />
      </div>

      {/* Table */}
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left px-4 py-2 text-sm font-medium text-gray-600">
                Variable
              </th>
              <th className="text-left px-4 py-2 text-sm font-medium text-gray-600">
                Before
              </th>
              <th className="text-left px-4 py-2 text-sm font-medium text-gray-600">
                After
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data.changes.map((change, index) => (
              <DiffRow
                key={index}
                change={change}
                showHex={showHex}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Link to full storage */}
      <div className="mt-4 text-center">
        <a
          href={`/${chainId}/${address}?block=${data.block_number}`}
          className="text-blue-600 hover:underline text-sm"
        >
          View full storage at block {data.block_number.toLocaleString()}
        </a>
      </div>
    </div>
  );
}
```

### ValueDisplay

```tsx
// src/components/storage/ValueDisplay.tsx

'use client';

import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { Tooltip } from '@/components/ui/Tooltip';
import { cn } from '@/lib/utils';

interface ValueDisplayProps {
  value: string;
  rawValue: string;
  typeLabel?: string;
  className?: string;
}

export function ValueDisplay({ value, rawValue, typeLabel, className }: ValueDisplayProps) {
  const [copied, setCopied] = useState(false);

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(rawValue);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Determine display style based on type
  const isAddress = typeLabel?.includes('address') || value.match(/^0x[a-fA-F0-9]{40}$/);
  const isBool = typeLabel?.includes('bool');
  const isNumber = !isAddress && !isBool && /^[\d,\.]+$/.test(value);

  return (
    <div className={cn("flex items-center gap-2 group", className)}>
      <Tooltip content={rawValue}>
        <span className={cn(
          "font-mono",
          isAddress && "text-blue-600",
          isBool && (value === 'true' ? "text-green-600" : "text-gray-500"),
          isNumber && "text-purple-600"
        )}>
          {value}
        </span>
      </Tooltip>

      <button
        onClick={copyToClipboard}
        className="opacity-0 group-hover:opacity-100 transition-opacity"
      >
        {copied ? (
          <Check className="w-4 h-4 text-green-500" />
        ) : (
          <Copy className="w-4 h-4 text-gray-400 hover:text-gray-600" />
        )}
      </button>
    </div>
  );
}
```

## API Client

```typescript
// src/lib/api.ts

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

export async function fetchContract(chainId: string, address: string) {
  const res = await fetch(`${API_BASE}/contracts/${chainId}/${address}`);
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || 'Failed to fetch contract');
  }
  return res.json();
}

export async function fetchStorage(
  chainId: string,
  address: string,
  block?: number,
  mappingKeys?: Record<number, string[]>
) {
  const params = new URLSearchParams();
  params.set('block', block?.toString() || 'latest');
  if (mappingKeys) {
    params.set('mapping_keys', JSON.stringify(mappingKeys));
  }

  const res = await fetch(
    `${API_BASE}/storage/${chainId}/${address}?${params}`
  );
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || 'Failed to fetch storage');
  }
  return res.json();
}

export async function fetchTxDiff(
  chainId: string,
  address: string,
  txHash: string
) {
  const res = await fetch(`${API_BASE}/tx/${chainId}/${address}/${txHash}`);
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || 'Failed to fetch transaction');
  }
  return res.json();
}
```

## React Query Hooks

```typescript
// src/lib/hooks/useContract.ts

import { useQuery } from '@tanstack/react-query';
import { fetchContract } from '../api';

export function useContract(chainId: string, address: string) {
  return useQuery({
    queryKey: ['contract', chainId, address],
    queryFn: () => fetchContract(chainId, address),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}


// src/lib/hooks/useStorage.ts

import { useQuery } from '@tanstack/react-query';
import { fetchStorage } from '../api';

export function useStorage(
  chainId: string,
  address: string,
  block?: number,
  mappingKeys?: Record<number, string[]>
) {
  return useQuery({
    queryKey: ['storage', chainId, address, block, mappingKeys],
    queryFn: () => fetchStorage(chainId, address, block, mappingKeys),
    staleTime: 60 * 1000, // 1 minute
  });
}


// src/lib/hooks/useTxDiff.ts

import { useQuery } from '@tanstack/react-query';
import { fetchTxDiff } from '../api';

export function useTxDiff(chainId: string, address: string, txHash: string) {
  return useQuery({
    queryKey: ['txDiff', chainId, address, txHash],
    queryFn: () => fetchTxDiff(chainId, address, txHash),
    staleTime: Infinity, // Transaction data never changes
  });
}
```

## Styling (Tailwind Config)

```javascript
// tailwind.config.js

module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Custom colors matching design spec
        primary: '#3B82F6',
        secondary: '#6B7280',
        background: '#FAFAFA',
        foreground: '#1A1A1A',
        border: '#E5E7EB',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
};
```

## Global Styles

```css
/* src/app/globals.css */

@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  body {
    @apply bg-background text-foreground;
  }

  /* Custom scrollbar */
  ::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }

  ::-webkit-scrollbar-track {
    @apply bg-gray-100;
  }

  ::-webkit-scrollbar-thumb {
    @apply bg-gray-300 rounded;
  }

  ::-webkit-scrollbar-thumb:hover {
    @apply bg-gray-400;
  }
}

@layer components {
  /* Storage tree indentation lines */
  .tree-line {
    @apply border-l border-gray-200;
  }
}
```

## Testing Strategy

### Unit Tests (Vitest + Testing Library)

1. **Component rendering**
   - SearchForm validation
   - TreeNode expand/collapse
   - ValueDisplay formatting

2. **Hooks**
   - Loading states
   - Error handling
   - Data transformation

### E2E Tests (Playwright)

1. **Search flow**
   - Enter address -> navigate -> see storage

2. **Storage exploration**
   - Expand tree nodes
   - Change block number
   - Add mapping key

3. **Transaction diff**
   - View changes
   - Toggle hex view

## Build & Run

```bash
# Development
npm run dev

# Build
npm run build

# Production
npm start

# Tests
npm test
npm run test:e2e
```

## Environment Variables

```env
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```
