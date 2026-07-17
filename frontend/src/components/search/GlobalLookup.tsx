'use client';

import { FormEvent, useState } from 'react';
import { Search } from 'lucide-react';
import { usePathname, useRouter } from 'next/navigation';
import { inspectionPath } from '@/lib/navigation';
import { saveRecentInspection } from '@/lib/utils';

export function GlobalLookup() {
  const pathname = usePathname();
  const router = useRouter();
  const [value, setValue] = useState('');
  const [invalid, setInvalid] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  if (pathname === '/') return null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const destination = inspectionPath(value);
    if (!destination) {
      setInvalid(true);
      return;
    }
    const normalized = value.trim();
    saveRecentInspection({
      chain: '1',
      kind: normalized.length === 66 ? 'transaction' : 'contract',
      value: normalized,
    });
    setValue('');
    setInvalid(false);
    setMobileOpen(false);
    router.push(destination);
  };

  const input = (id: string, autoFocus = false) => (
    <>
      <label htmlFor={id} className="sr-only">Contract address or transaction hash</label>
      <input
        id={id}
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setInvalid(false);
        }}
        autoFocus={autoFocus}
        aria-invalid={invalid}
        title={invalid ? 'Enter a contract address or transaction hash' : undefined}
        placeholder="Address or transaction hash"
        className="h-8 min-w-0 flex-1 border border-gray-300 bg-white px-2 text-xs placeholder:text-gray-500 focus:border-black focus:outline-none"
      />
      <button type="submit" className="h-8 border-y border-r border-gray-300 px-3 text-xs text-gray-700 hover:bg-gray-100">
        Search
      </button>
    </>
  );

  return (
    <>
      <form onSubmit={submit} className="hidden w-full max-w-sm items-center sm:flex">
        {input('global-lookup')}
      </form>
      <button
        type="button"
        aria-label={mobileOpen ? 'Close search' : 'Search'}
        aria-expanded={mobileOpen}
        onClick={() => setMobileOpen((open) => !open)}
        className="touch-hitbox inline-flex h-8 w-8 items-center justify-center text-gray-500 hover:text-gray-900 sm:hidden"
      >
        <Search size={16} strokeWidth={1.25} />
      </button>
      {mobileOpen && (
        <form
          onSubmit={submit}
          className="absolute inset-x-0 top-full z-20 flex items-center border-b border-gray-300 bg-white px-4 py-2 sm:hidden"
          data-testid="mobile-lookup"
        >
          {input('global-lookup-mobile', true)}
        </form>
      )}
    </>
  );
}
