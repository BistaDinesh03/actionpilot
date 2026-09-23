import { defineConfig } from '@playwright/test';

// Runs Playwright tests exported from ActionPilot (Skills -> Playwright).
// Usage: npx playwright test <skill-name>.spec.ts --project=chromium
export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
