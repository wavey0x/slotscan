import { expect, test } from '@playwright/test';

const SIMPLE_TX = '0x711899730951bad9b5b29d16c0ffd0be3a7aefcd96b9e1d376619f02bdd9c1d3';
const RESTORED_TX = '0x7fe79d06862f71a5809babfadac1c9a204b09dfbb8c40ac725d23b9bae2b7cac';
const REVERTED_WRITES_TX = '0x561dd631cb9eabc2ba595ca4410fd26ca3e6183d2b8ba4f55bbf4c4b9c742ae2';
const SOURCE_LAYOUT_TX = '0x3353c2009d984e15a2dd909d09f56f2833cfa99129fa834ea6eaf9349f14cd60';
const NESTED_STRUCT_MAPPING_TX = '0x8e37bdd5003c883a684cd6c944c5fac24cc7f29b15ef23c5f6d7adf41c222f82';
const GNOSIS_SAFE_ADDRESS = '0x16388463d60ffe0661cf7f1f31a7d658ac790ff7';
const LIDO_ADDRESS = '0xae7ab96520de3a18e5e111b5eaab095312d7fe84';

test('home search accepts a transaction hash and opens transaction-wide history', async ({ page }) => {
  await page.goto('/');
  await page.getByPlaceholder('Contract address or transaction hash (0x...)').fill(SIMPLE_TX);
  await page.getByRole('button', { name: 'Analyze Storage' }).click();

  await expect(page).toHaveURL(`/1/tx/${SIMPLE_TX}`);
  await expect(page.getByRole('heading', { name: 'Transaction storage history' })).toBeVisible();
  await expect(page.getByTestId('summary-writes').getByText('2', { exact: true })).toBeVisible();
  await expect(page.getByTestId('summary-slots').getByText('2', { exact: true })).toBeVisible();
  for (const label of ['Transaction', 'Block', 'From', 'To']) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByRole('button', { name: 'Grouped' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Net effects' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Restored' })).toHaveCount(0);
  await expect(page.getByText('HEX', { exact: true })).toHaveCount(0);
});

test('all writes remain visible without interpretive classification controls', async ({ page }) => {
  await page.goto(`/1/tx/${RESTORED_TX}`);

  await expect(page.getByRole('heading', { name: 'Transaction storage history' })).toBeVisible();
  await expect(page.getByTestId('summary-writes').getByText('5', { exact: true })).toBeVisible();
  await expect(page.getByTestId('summary-slots').getByText('4', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Grouped' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByTestId('contract-toggle').click();
  for (const step of ['719', '777', '920', '1432']) {
    await expect(page.getByText(step, { exact: true })).toBeVisible();
  }

  await page.getByRole('button', { name: 'Expand write history' }).click();
  await expect(page.getByText('1496', { exact: true })).toBeVisible();
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

test('verified sources recover proxy, namespace, legacy, and Vyper variable names', async ({ page }) => {
  await page.goto(`/1/tx/${SOURCE_LAYOUT_TX}`);

  await expect(page.getByTestId('summary-writes').getByText('74', { exact: true })).toBeVisible();
  await expect(page.getByTestId('summary-slots').getByText('51', { exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Storage owners' })).toHaveCount(0);
  await expect(page.getByTestId('contract-toggle')).toHaveCount(13);
  for (const toggle of await page.getByTestId('contract-toggle').all()) {
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  }
  await expect(page.getByRole('heading', { name: 'GnosisSafe' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'YearnV3Vault' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Vat' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'WithdrawalQueueERC721' })).toBeVisible();

  await expect(page.getByText('Contract', { exact: true })).toBeVisible();
  await expect(page.getByText('Activity', { exact: true })).toBeVisible();
  const safeSection = page.getByRole('heading', { name: 'GnosisSafe' }).locator('xpath=ancestor::section');
  await expect(safeSection.getByText('0x1638...0ff7', { exact: true })).toBeVisible();
  await expect(safeSection.getByRole('button', { name: 'Copy' })).toBeVisible();

  const search = page.getByPlaceholder('Search contract, address, slot, or variable');
  await search.fill('nonreentrant.lock');
  await expect(page.getByTestId('contract-toggle')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByText('nonreentrant.lock', { exact: true })).toBeVisible();

  const valueDiff = page.getByTestId('value-diff').first();
  const beforeBox = await valueDiff.getByTestId('value-before').boundingBox();
  const afterBox = await valueDiff.getByTestId('value-after').boundingBox();
  const arrowBox = await valueDiff.getByTestId('value-arrow').boundingBox();
  expect(beforeBox).not.toBeNull();
  expect(afterBox).not.toBeNull();
  expect(arrowBox).not.toBeNull();
  expect(Math.abs(beforeBox!.x - afterBox!.x)).toBeLessThan(1);
  expect(Math.abs(beforeBox!.y - arrowBox!.y)).toBeLessThan(1);
  expect(arrowBox!.x).toBeGreaterThanOrEqual(beforeBox!.x + beforeBox!.width);
  expect(afterBox!.y).toBeGreaterThan(beforeBox!.y);

  await search.fill('current_debt');
  await expect(page.getByText('current_debt', { exact: true })).toHaveCount(2);

  await search.fill('lastRequestId');
  await expect(page.getByText('lastRequestId', { exact: true })).toBeVisible();
});

test('nested mappings inside mapping structs show the full resolved path', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto(`/1/tx/${NESTED_STRUCT_MAPPING_TX}`);

  const search = page.getByPlaceholder('Search contract, address, slot, or variable');
  await search.fill('lastExecutionTimestamp');

  await expect(page.getByRole('heading', { name: 'borgCore' })).toBeVisible();
  const variable = page.getByTestId('keyed-variable-path');
  await expect(variable.getByText('lastExecutionTimestamp', { exact: true })).toBeVisible();
  await expect(variable.getByText('policy', { exact: true })).toBeVisible();
  await expect(variable.getByText('0x40a2...130d', { exact: true })).toBeVisible();
  await expect(variable.getByText('methods', { exact: true })).toBeVisible();
  await expect(variable.getByText('0x8d80ff0a', { exact: true })).toBeVisible();
  await expect(variable.getByText('uint256', { exact: true })).toBeVisible();
  await expect(variable.getByText('PolicyItem', { exact: true })).toHaveCount(0);

  const primaryBox = await variable.getByTestId('keyed-variable-primary').boundingBox();
  const contextBox = await variable.getByTestId('keyed-variable-context').boundingBox();
  const nestedKeyLines = variable.getByTestId('keyed-variable-key-line');
  await expect(nestedKeyLines).toHaveCount(2);
  const policyLineBox = await nestedKeyLines.nth(0).boundingBox();
  const methodsLineBox = await nestedKeyLines.nth(1).boundingBox();
  expect(primaryBox).not.toBeNull();
  expect(contextBox).not.toBeNull();
  expect(policyLineBox).not.toBeNull();
  expect(methodsLineBox).not.toBeNull();
  expect(contextBox!.y).toBeGreaterThan(primaryBox!.y);
  expect(methodsLineBox!.y).toBeGreaterThan(policyLineBox!.y);

  const copy = variable.getByRole('button', { name: 'Copy full path' });
  await expect(copy).toBeVisible();
  await copy.click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(
    'policy[0x40a2accbd92bca938b02010e17a5b8929b49130d].methods[0x8d80ff0a].lastExecutionTimestamp',
  );

  await page.getByRole('button', { name: 'Timeline' }).click();
  await expect(page).toHaveURL(new RegExp(`/${NESTED_STRUCT_MAPPING_TX}\\?.*view=timeline`));
  const timelineVariable = page.getByTestId('keyed-variable-path');
  await expect(timelineVariable.getByTestId('keyed-variable-primary')).toHaveText('lastExecutionTimestamp');
  await expect(timelineVariable.getByTestId('keyed-variable-key-line')).toHaveCount(2);
});

test('multi-key mappings stay compact and copy their complete path', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto(`/1/tx/${SOURCE_LAYOUT_TX}?focus=${LIDO_ADDRESS}`);

  await expect(page.getByRole('heading', { name: 'Transaction storage history' })).toBeVisible();
  const lidoSection = page.getByRole('heading', { name: 'Lido' }).locator('xpath=ancestor::section');
  await expect(lidoSection.getByTestId('contract-toggle')).toHaveAttribute('aria-expanded', 'true');
  const keyedVariables = lidoSection.getByTestId('keyed-variable-path');
  await expect(keyedVariables).toHaveCount(3);

  const allowance = keyedVariables.filter({ hasText: 'allowances' }).first();
  await expect(allowance.getByTestId('keyed-variable-primary')).toHaveText('allowances');
  await expect(allowance.getByText('0x470e...7435', { exact: true })).toBeVisible();
  await expect(allowance.getByText('0x889e...f9b1', { exact: true })).toBeVisible();
  await expect(allowance.getByText('uint256', { exact: true })).toBeVisible();
  await expect(allowance).not.toContainText('0x470e0e048f85cfd72eef325895e02c8d297e7435');

  const keyLines = allowance.getByTestId('keyed-variable-key-line');
  await expect(keyLines).toHaveCount(2);
  const firstKeyBox = await keyLines.nth(0).boundingBox();
  const secondKeyBox = await keyLines.nth(1).boundingBox();
  expect(firstKeyBox).not.toBeNull();
  expect(secondKeyBox).not.toBeNull();
  expect(secondKeyBox!.y).toBeGreaterThan(firstKeyBox!.y);
  expect(Math.abs(secondKeyBox!.x - firstKeyBox!.x)).toBeLessThan(1);

  const shares = keyedVariables.filter({ hasText: 'shares' }).first();
  await expect(shares.getByTestId('keyed-variable-key-line')).toHaveCount(0);
  await expect(shares.getByTestId('keyed-variable-primary')).toContainText('shares[0x470e...7435]');

  const copy = allowance.getByRole('button', { name: 'Copy full path' });
  await copy.click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(
    'allowances[0x470e0e048f85cfd72eef325895e02c8d297e7435][0x889edc2edab5f40e902b864ad4d7ade8e412f9b1]',
  );
});

test('legacy contract transaction URLs redirect to the complete focused report', async ({ page }) => {
  await page.goto(`/1/${GNOSIS_SAFE_ADDRESS}?tx=${SOURCE_LAYOUT_TX}`);
  await expect(page).toHaveURL(`/1/tx/${SOURCE_LAYOUT_TX}?focus=${GNOSIS_SAFE_ADDRESS}`);
  await expect(page.getByTestId('contract-toggle')).toHaveCount(13);
  const safeSection = page.getByRole('heading', { name: 'GnosisSafe' }).locator('xpath=ancestor::section');
  await expect(safeSection.getByTestId('contract-toggle')).toHaveAttribute('aria-expanded', 'true');

  await page.goto(`/1/${GNOSIS_SAFE_ADDRESS}/tx/${SOURCE_LAYOUT_TX}`);
  await expect(page).toHaveURL(`/1/tx/${SOURCE_LAYOUT_TX}?focus=${GNOSIS_SAFE_ADDRESS}`);
});
