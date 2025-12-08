import Link from 'next/link';
import Image from 'next/image';
import icon from '@/app/icon.svg';

export function Header() {
  return (
    <header className="border-b border-gray-300">
      <div className="mx-auto max-w-4xl px-8 py-4">
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
      </div>
    </header>
  );
}
