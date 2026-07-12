import { redirect } from 'next/navigation';
import { ContractPage } from '@/components/contract/ContractPage';
import { PageFrame } from '@/components/layout/PageFrame';

interface ContractRouteProps {
  params: { chain: string; address: string };
  searchParams: { tx?: string | string[] };
}

export default function ContractRoute({ params, searchParams }: ContractRouteProps) {
  const txHash = Array.isArray(searchParams.tx) ? searchParams.tx[0] : searchParams.tx;
  if (txHash && /^0x[a-fA-F0-9]{64}$/.test(txHash)) {
    redirect(`/${params.chain}/tx/${txHash}?focus=${params.address}`);
  }

  return (
    <PageFrame>
      <ContractPage chain={params.chain} address={params.address} />
    </PageFrame>
  );
}
