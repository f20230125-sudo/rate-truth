import { defineConfig, devices } from "@playwright/test";

// Production server on 3171; every API request is intercepted from test fixtures.
// A remote build may be tested with BASE_URL. No backend is needed.
const remote = process.env.BASE_URL;
const local = "http://127.0.0.1:3171";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: { baseURL: remote ?? local, trace: "retain-on-failure", reducedMotion: "reduce" },
  projects: [
    {
      name: "desktop",
      testIgnore: /live\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    { name: "phone", testIgnore: /live\.spec\.ts/, use: { ...devices["Pixel 7"] } },
    { name: "live", testMatch: /live\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: remote
    ? undefined
    : {
        command: "node node_modules/next/dist/bin/next start -p 3171 -H 127.0.0.1",
        url: local,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
        env: { NEXT_PUBLIC_SITE_URL: local },
      },
});
