import { ContractPage } from '@/components/contract/ContractPage';
import { PageFrame } from '@/components/layout/PageFrame';

interface ContractRouteProps {
  params: { chain: string; address: string };
}

export default function ContractRoute({ params }: ContractRouteProps) {
  return (
    <PageFrame>
      <ContractPage chain={params.chain} address={params.address} />
    </PageFrame>
  );
}
