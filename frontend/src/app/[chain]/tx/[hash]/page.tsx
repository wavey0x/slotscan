import { PageFrame } from '@/components/layout/PageFrame';
import { TransactionStorageExplorer } from '@/components/transaction/TransactionStorageExplorer';

interface TransactionPageProps {
  params: { chain: string; hash: string };
}

export default function TransactionPage({ params }: TransactionPageProps) {
  return (
    <PageFrame>
      <TransactionStorageExplorer chain={params.chain} txHash={params.hash} />
    </PageFrame>
  );
}
