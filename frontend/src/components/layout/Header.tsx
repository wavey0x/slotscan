import Link from 'next/link';
import Image from 'next/image';
import icon from '@/app/icon.svg';
import { GlobalLookup } from '@/components/search/GlobalLookup';

export function Header() {
  return (
    <header className="border-b border-gray-300">
      <div className="mx-auto flex min-h-16 w-full max-w-[90rem] items-center justify-between gap-6 px-4 py-3 sm:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-2 text-base text-gray-900 no-underline hover:no-underline">
          <Image
            src={icon}
            alt="SlotScan logo"
            width={32}
            height={32}
            priority
            className="shrink-0"
          />
          <span>SlotScan</span>
        </Link>
        <GlobalLookup />
      </div>
    </header>
  );
}
