import { Container } from '@/components/layout/Container';
import { SearchForm } from '@/components/search/SearchForm';
import { RecentSearches } from '@/components/search/RecentSearches';

export default function HomePage() {
  return (
    <Container>
      <div className="flex flex-col items-center justify-center min-h-[50vh]">
        <h1 className="text-2xl font-light mb-1 text-gray-900">SlotScan</h1>
        <p className="text-sm text-gray-500 mb-8">Ethereum Storage Analyzer</p>
        <SearchForm />
        <RecentSearches className="mt-12 w-full max-w-lg" />
      </div>
    </Container>
  );
}
