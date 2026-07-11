import { expect, test } from '@playwright/test';

const SIMPLE_TX = '0x711899730951bad9b5b29d16c0ffd0be3a7aefcd96b9e1d376619f02bdd9c1d3';
const RESTORED_TX = '0x7fe79d06862f71a5809babfadac1c9a204b09dfbb8c40ac725d23b9bae2b7cac';
const REVERTED_WRITES_TX = '0x561dd631cb9eabc2ba595ca4410fd26ca3e6183d2b8ba4f55bbf4c4b9c742ae2';

test('home search accepts a transaction hash and opens transaction-wide history', async ({ page }) => {
  await page.goto('/');
  await page.getByPlaceholder('Contract address or transaction hash (0x...)').fill(SIMPLE_TX);
  await page.getByRole('button', { name: 'Analyze Storage' }).click();

  await expect(page).toHaveURL(`/1/tx/${SIMPLE_TX}`);
  await expect(page.getByRole('heading', { name: 'Transaction storage history' })).toBeVisible();
  await expect(page.getByText('TetherToken')).toBeVisible();
  await expect(page.getByText('2 writes · 2 slots')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Timeline' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Net effects' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Restored' })).toHaveCount(0);
  await expect(page.getByText('HEX', { exact: true })).toHaveCount(0);
});

test('all writes remain visible without interpretive classification controls', async ({ page }) => {
  await page.goto(`/1/tx/${RESTORED_TX}`);

  await expect(page.getByRole('heading', { name: 'Transaction storage history' })).toBeVisible();
  await expect(page.getByText('Chromia', { exact: true })).toHaveCount(1);
  await expect(page.getByText('5 writes · 4 slots')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Timeline' })).toHaveAttribute('aria-pressed', 'true');
  for (const step of ['719', '777', '920', '1432', '1496']) {
    await expect(page.getByText(step, { exact: true })).toBeVisible();
  }

  await page.getByRole('button', { name: 'Grouped' }).click();
  await page.getByRole('button', { name: 'Expand write history' }).click();
  await expect(page.getByText('1/2')).toBeVisible();
  await expect(page.getByText('2/2')).toBeVisible();
  await expect(page.getByText('restored', { exact: true })).toHaveCount(0);
});

test('reverted child writes remain grouped and in the global timeline', async ({ page }) => {
  await page.goto(`/1/tx/${REVERTED_WRITES_TX}`);

  await expect(page.getByRole('heading', { name: 'Transaction storage history' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Grouped' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByPlaceholder('Search contract, address, slot, or variable')).toBeVisible();
  await expect(page.getByText(/reverted writes?/, { exact: true }).first()).toBeVisible();

  await page.getByRole('button', { name: 'Timeline' }).click();
  await expect(page.getByTestId('timeline-event')).toHaveCount(386);
  await expect(page.getByText('reverted', { exact: true }).first()).toBeVisible();
});
