import { defineConfig, devices } from '@playwright/test';
import { rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const databasePath = join(
  tmpdir(),
  `slotscan-playwright-${process.pid}.sqlite3`,
);

process.once('exit', () => {
  for (const path of [databasePath, `${databasePath}-wal`, `${databasePath}-shm`]) {
    rmSync(path, { force: true });
  }
});

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3001',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command:
        'venv/bin/alembic upgrade head && ' +
        'venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000',
      cwd: '../backend',
      env: { DATABASE_PATH: databasePath },
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: 'npm run dev -- --port 3001',
      cwd: '.',
      url: 'http://127.0.0.1:3001',
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
