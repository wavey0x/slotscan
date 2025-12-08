'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

interface TxDiffPageProps {
  params: { chain: string; address: string; hash: string };
}

// Redirect to the query param format
export default function TxDiffPage({ params }: TxDiffPageProps) {
  const { chain, address, hash } = params;
  const router = useRouter();

  useEffect(() => {
    router.replace(`/${chain}/${address}?tx=${hash}`);
  }, [chain, address, hash, router]);

  return null;
}
