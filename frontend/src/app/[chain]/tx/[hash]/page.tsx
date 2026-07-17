import { PageFrame } from '@/components/layout/PageFrame';
import { TransactionStorageExplorer } from '@/components/transaction/TransactionStorageExplorer';

interface TransactionPageProps {
  params: Promise<{ chain: string; hash: string }>;
}

export default async function TransactionPage({ params }: TransactionPageProps) {
  const { chain, hash } = await params;
  return (
    <PageFrame>
      <TransactionStorageExplorer chain={chain} txHash={hash} />
    </PageFrame>
  );
}
