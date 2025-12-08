'use client';

import { useState } from 'react';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';

interface BlockSelectorProps {
  currentBlock?: number;
  onBlockChange: (block: number) => void;
}

export function BlockSelector({ currentBlock, onBlockChange }: BlockSelectorProps) {
  const [blockInput, setBlockInput] = useState(currentBlock?.toString() || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const block = parseInt(blockInput);
    if (!isNaN(block) && block >= 0) {
      onBlockChange(block);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex gap-1">
      <Input
        type="number"
        value={blockInput}
        onChange={(e) => setBlockInput(e.target.value)}
        placeholder="Block"
        className="w-32"
        min={0}
      />
      <Button type="submit" variant="secondary" size="sm">
        Go
      </Button>
    </form>
  );
}
