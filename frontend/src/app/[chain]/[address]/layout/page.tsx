import { redirect } from 'next/navigation';

interface LayoutPageProps {
  params: { chain: string; address: string };
}

export default function LayoutPage({ params }: LayoutPageProps) {
  const { chain, address } = params;
  redirect(`/${chain}/${address}`);
}
