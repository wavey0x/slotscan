'use client';

import { Moon, Sun } from 'lucide-react';
import { useEffect, useState } from 'react';

type Theme = 'light' | 'dark';

const STORAGE_KEY = 'slotscan-theme';
const THEME_EVENT = 'slotscan-theme-change';

function savedTheme(): Theme | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === 'light' || saved === 'dark' ? saved : null;
  } catch {
    return null;
  }
}

function appliedTheme(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

function applyTheme(theme: Theme, persist = false) {
  const root = document.documentElement;
  root.classList.toggle('dark', theme === 'dark');
  root.style.colorScheme = theme;
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // The current page can still change theme when storage is unavailable.
    }
  }
  window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: theme }));
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const syncTheme = () => setTheme(appliedTheme());
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const followSystemTheme = (event: MediaQueryListEvent) => {
      if (savedTheme()) return;
      applyTheme(event.matches ? 'dark' : 'light');
    };
    const syncAcrossTabs = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY) return;
      const next = event.newValue === 'light' || event.newValue === 'dark'
        ? event.newValue
        : (media.matches ? 'dark' : 'light');
      applyTheme(next);
    };

    syncTheme();
    window.addEventListener(THEME_EVENT, syncTheme);
    window.addEventListener('storage', syncAcrossTabs);
    media.addEventListener('change', followSystemTheme);
    return () => {
      window.removeEventListener(THEME_EVENT, syncTheme);
      window.removeEventListener('storage', syncAcrossTabs);
      media.removeEventListener('change', followSystemTheme);
    };
  }, []);

  const nextTheme = theme === 'dark' ? 'light' : 'dark';
  const label = theme === null
    ? 'Toggle color theme'
    : `Switch to ${nextTheme} mode`;

  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={theme === 'dark'}
      title={label}
      className="inline-flex h-8 w-8 shrink-0 items-center justify-center border border-gray-300 text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900"
      onClick={() => {
        const next = appliedTheme() === 'dark' ? 'light' : 'dark';
        applyTheme(next, true);
        setTheme(next);
      }}
    >
      <Moon aria-hidden="true" className="h-4 w-4 dark:hidden" strokeWidth={1.5} />
      <Sun aria-hidden="true" className="hidden h-4 w-4 dark:block" strokeWidth={1.5} />
    </button>
  );
}
