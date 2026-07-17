import { LayoutComparisonPage } from '@/components/comparison/LayoutComparisonPage';
import { PageFrame } from '@/components/layout/PageFrame';

interface ComparisonRouteProps {
  params: Promise<{ chain: string }>;
}

export default async function ComparisonRoute({
  params,
}: ComparisonRouteProps) {
  const { chain } = await params;
  return (
    <PageFrame>
      <LayoutComparisonPage chain={chain} />
    </PageFrame>
  );
}
