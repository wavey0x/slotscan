import { Container } from '@/components/layout/Container';
import { TransactionStorageExplorer } from '@/components/transaction/TransactionStorageExplorer';

interface TransactionPageProps {
  params: { chain: string; hash: string };
}

export default function TransactionPage({ params }: TransactionPageProps) {
  return (
    <Container>
      <TransactionStorageExplorer chain={params.chain} txHash={params.hash} />
    </Container>
  );
}
