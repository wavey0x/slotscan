'use client';

import { useState } from 'react';
import { Container } from '@/components/layout/Container';
import { ContractNav } from '@/components/layout/ContractNav';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { Loading } from '@/components/ui/Loading';
import { LayoutTable } from '@/components/layout/LayoutTable';
import { useLayout } from '@/lib/hooks/useLayout';

interface LayoutPageProps {
  params: { chain: string; address: string };
}

export default function LayoutPage({ params }: LayoutPageProps) {
  const { chain, address } = params;

  const [blockInput, setBlockInput] = useState<string>('');
  const [block, setBlock] = useState<number | 'latest'>('latest');
  const [blockError, setBlockError] = useState<string | null>(null);

  // Only fetch layout - no heavy storage or contract metadata calls
  const { data: layout, isLoading: layoutLoading, error: layoutError } = useLayout(chain, address);

  // Contract name comes from layout response
  const contractName = layout?.contract_name;

  const handleBlockSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const value = blockInput.trim();

    if (!value || value.toLowerCase() === 'latest') {
      setBlock('latest');
      setBlockError(null);
      return;
    }

    const num = parseInt(value, 10);
    if (isNaN(num) || num < 0) {
      setBlockError('Invalid block number');
      return;
    }

    setBlock(num);
    setBlockError(null);
  };

  // Handle layout loading errors
  if (layoutError) {
    return (
      <Container>
        <ContractNav chain={chain} address={address} contractName={contractName} />
        <div className="p-6 border border-gray-300">
          <div className="text-gray-900 mb-2">Storage layout not available</div>
          <p className="text-sm text-gray-500">
            Contract may not be verified or source code is unavailable.
          </p>
        </div>
      </Container>
    );
  }

  // Loading state
  if (layoutLoading) {
    return (
      <Container>
        <ContractNav chain={chain} address={address} contractName={contractName} />
        <Loading
          messages={[
            'Fetching contract',
            'Loading storage layout',
            'Parsing variable types',
          ]}
        />
      </Container>
    );
  }

  return (
    <Container>
      <ContractNav chain={chain} address={address} contractName={contractName} />

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-medium text-gray-900">Storage Layout</h1>

        {/* Block selector */}
        <form onSubmit={handleBlockSubmit} className="flex items-center gap-2">
          <span className="text-sm text-gray-500">Block:</span>
          <Input
            type="text"
            value={blockInput}
            onChange={(e) => {
              setBlockInput(e.target.value);
              setBlockError(null);
            }}
            placeholder="latest"
            className="w-32 h-7 text-xs font-mono"
          />
          <Button type="submit" variant="secondary" size="sm" className="h-7 text-xs">
            Go
          </Button>
          {block !== 'latest' && (
            <span className="text-xs text-gray-500 ml-1">
              ({block.toLocaleString()})
            </span>
          )}
          {blockError && <span className="text-red text-xs ml-2">{blockError}</span>}
        </form>
      </div>

      {/* Layout Table */}
      {layout ? (
        <LayoutTable
          chainId={chain}
          address={address}
          block={block}
          layout={layout}
        />
      ) : (
        <div className="p-6 border border-gray-300 text-gray-500">
          No storage layout available
        </div>
      )}
    </Container>
  );
}
