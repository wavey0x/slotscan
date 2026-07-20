import { expect, test } from '@playwright/test';

const ADDRESS = '0x1234567890abcdef1234567890abcdef12345678';
const TX_HASH = `0x${'12'.repeat(32)}`;
const STORAGE_KEY = 'slotscan_recent_inspections';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/slotscan/**', async (route) => {
    await route.fulfill({
      status: 404,
      json: {
        detail: {
          error: 'Not found',
          code: 'NOT_FOUND',
        },
      },
    });
  });
});

test('not-found transactions stay out of recently viewed', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(({ key, txHash }) => {
    localStorage.setItem(key, JSON.stringify([{
      chain: '1',
      kind: 'transaction',
      value: txHash,
      timestamp: Date.now(),
    }]));
  }, { key: STORAGE_KEY, txHash: TX_HASH });

  await page.goto(`/1/tx/${TX_HASH}`);
  await expect(page.getByText(
    'Failed to analyze transaction: Not found',
    { exact: true },
  )).toBeVisible();
  expect(await page.evaluate((key) => {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored).length : 0;
  }, STORAGE_KEY)).toBe(0);

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Recent' })).toHaveCount(0);
});

test('direct contract inspection links appear in recently viewed', async ({ page }) => {
  await page.goto(`/1/${ADDRESS}`);
  await expect.poll(() => page.evaluate((key) => {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored).length : 0;
  }, STORAGE_KEY)).toBe(1);

  await page.goto('/');

  const recent = page.locator('section').filter({
    has: page.getByRole('heading', { name: 'Recent' }),
  });
  const links = recent.getByRole('link');
  await expect(links).toHaveCount(1);
  await expect(links.nth(0)).toHaveAttribute('href', `/1/${ADDRESS}`);
});
