import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./browser",
  timeout: 20000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:4174",
    headless: true,
    launchOptions: process.env.CHROMIUM_EXECUTABLE
      ? {
          executablePath: process.env.CHROMIUM_EXECUTABLE,
          args: ["--no-sandbox", "--disable-dev-shm-usage"],
        }
      : {},
  },
  webServer: {
    command: "python3 -m http.server 4174 --bind 0.0.0.0 --directory web",
    url: "http://localhost:4174",
    reuseExistingServer: !process.env.CI,
  },
});
