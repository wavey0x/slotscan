import Link from 'next/link';

export function Header() {
  return (
    <header className="border-b border-gray-300">
      <div className="mx-auto max-w-4xl px-8 py-4">
        <Link href="/" className="text-base text-gray-900 no-underline hover:no-underline">
          StorageScan
        </Link>
      </div>
    </header>
  );
}
