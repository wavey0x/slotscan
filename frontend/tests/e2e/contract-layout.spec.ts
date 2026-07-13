import { expect, test } from '@playwright/test';

const VOTING_ESCROW_ADDRESS = '0x5f3b5dfeb7b28cdbd7faba78963ee202a494e2a2';

test('long slot indexes stay contained within the slot column', async ({ page }) => {
  await page.goto(`/1/${VOTING_ESCROW_ADDRESS}`);

  await expect(page.getByRole('heading', { name: 'Storage layout' })).toBeVisible();
  const row = page.getByText('nonreentrant.lock', { exact: true }).locator('xpath=ancestor::tr');
  const slotCell = row.getByTestId('layout-slot');
  const valueCell = row.locator('td').nth(4);

  await expect(slotCell).toHaveText('16777215');
  expect(await slotCell.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);

  const slotBox = await slotCell.boundingBox();
  const valueBox = await valueCell.boundingBox();
  expect(slotBox).not.toBeNull();
  expect(valueBox).not.toBeNull();
  expect(slotBox!.x + slotBox!.width).toBeLessThanOrEqual(valueBox!.x);
});
