import { ContractPage } from '@/components/contract/ContractPage';
import { PageFrame } from '@/components/layout/PageFrame';

interface ContractRouteProps {
  params: Promise<{ chain: string; address: string }>;
}

export default async function ContractRoute({ params }: ContractRouteProps) {
  const { chain, address } = await params;
  return (
    <PageFrame>
      <ContractPage chain={chain} address={address} />
    </PageFrame>
  );
}
