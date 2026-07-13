import type { Metadata } from 'next';
import { JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';
import { Header } from '@/components/layout/Header';

const mono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
});

const themeScript = `
  (() => {
    let saved = null;
    try { saved = localStorage.getItem('slotscan-theme'); } catch (_) {}
    const preference = saved === 'light' || saved === 'dark' ? saved : null;
    const dark = preference ? preference === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  })();
`;

export const metadata: Metadata = {
  title: 'SlotScan',
  description: 'Ethereum smart contract storage analyzer',
  metadataBase: new URL('https://slotscan.info'),
  openGraph: {
    title: 'SlotScan',
    description: 'Ethereum smart contract storage analyzer',
    siteName: 'SlotScan',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'SlotScan',
    description: 'Ethereum smart contract storage analyzer',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className={`${mono.variable} font-mono`}>
        <Providers>
          <Header />
          <main>{children}</main>
        </Providers>
      </body>
    </html>
  );
}
