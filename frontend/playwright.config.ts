import { defineConfig } from "@playwright/test";
import path from "node:path";
const python =
  process.platform === "win32"
    ? "../backend/.venv/Scripts/python.exe"
    : "../backend/.venv/bin/python";
export default defineConfig({
  testDir: "./e2e",
  timeout: 45000,
  expect: { timeout: 10000 },
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:8017",
    browserName: "chromium",
    channel: process.env.PLAYWRIGHT_CHANNEL || "chrome",
    headless: true,
    viewport: { width: 1440, height: 1024 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${path.resolve(python)}" ../scripts/e2e_server.py`,
    url: "http://127.0.0.1:8017/api/v1/health",
    reuseExistingServer: false,
    timeout: 30000,
  },
  reporter: [["list"]],
});
