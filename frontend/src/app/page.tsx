import { PageFrame } from '@/components/layout/PageFrame';
import { SearchForm } from '@/components/search/SearchForm';
import { RecentSearches } from '@/components/search/RecentSearches';

export default function HomePage() {
  return (
    <PageFrame variant="form">
      <div className="flex flex-col items-center justify-center min-h-[50vh]">
        <h1 className="mb-2 text-xl font-medium text-gray-900">Inspect Ethereum storage</h1>
        <p className="mb-8 text-center text-xs text-gray-500">Enter a contract address or transaction hash.</p>
        <SearchForm />
        <RecentSearches className="mt-12 w-full" />
      </div>
    </PageFrame>
  );
}
