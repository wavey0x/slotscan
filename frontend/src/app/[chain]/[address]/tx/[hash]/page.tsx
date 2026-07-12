import { redirect } from 'next/navigation';

interface TxDiffPageProps {
  params: { chain: string; address: string; hash: string };
}

export default function TxDiffPage({ params }: TxDiffPageProps) {
  redirect(`/${params.chain}/tx/${params.hash}?focus=${params.address}`);
}
