import { expect, test } from '@playwright/test';

test('theme toggle switches modes and keeps the explicit preference', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto('/');

  const toggle = page.getByRole('button', { name: 'Switch to dark mode' });
  await expect(toggle).toBeVisible();
  await expect(page.locator('html')).not.toHaveClass(/dark/);
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(255, 255, 255)');

  await toggle.click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await expect(page.getByRole('button', { name: 'Switch to light mode' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(38, 38, 38)');
  expect(await page.evaluate(() => localStorage.getItem('slotscan-theme'))).toBe('dark');

  await page.reload();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await expect(page.getByRole('button', { name: 'Switch to light mode' })).toBeVisible();
});
test('theme defaults to the system preference and remains available on result pages', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/');

  await expect(page.locator('html')).toHaveClass(/dark/);
  await expect(page.getByRole('button', { name: 'Switch to light mode' })).toBeVisible();

  const hash = `0x${'0'.repeat(64)}`;
  await page.goto(`/1/tx/${hash}`);
  await expect(page.getByRole('button', { name: 'Switch to light mode' })).toBeVisible();
});
