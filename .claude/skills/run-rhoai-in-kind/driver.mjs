#!/usr/bin/env node
// Drives the ODH Dashboard running on the local kind cluster with Playwright.
// Requires `npx playwright` (chromium) available - see SKILL.md Prerequisites.
//
// Usage:
//   node driver.mjs login-screenshot [output.png]
//
// Reads credentials from test-variables.yml (repo root) TEST_USER block.

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const DASHBOARD_URL = "https://rhods-dashboard.127.0.0.1.sslip.io/";

function readTestVariables() {
  const raw = fs.readFileSync(path.join(REPO_ROOT, "test-variables.yml"), "utf8");
  // Minimal YAML scrape - avoids adding a yaml dependency for 3 fields.
  // OCP_ADMIN_USER (adm-auth), not TEST_USER (foo-auth) - foo-auth isn't a real IDP
  // in this repo's local oauth-server setup (components/opendatahub-tests/openldap.yaml
  // configures adm-auth/contributor-auth/ldap-provider-qe); confirmed by fetching the
  // actual oauth-server login page and reading its rendered IDP links.
  const block = raw.split(/^OCP_ADMIN_USER:/m)[1].split(/^\S/m)[0];
  const get = (key) => block.match(new RegExp(`${key}:\\s*(\\S+)`))[1].replace(/^["']|["']$/g, "");
  return { authType: get("AUTH_TYPE"), username: get("USERNAME"), password: get("PASSWORD") };
}

async function loginScreenshot(outPath) {
  const { authType, username, password } = readTestVariables();
  const browser = await chromium.launch();
  // ignoreHTTPSErrors: the dashboard's oauth-proxy serves a self-signed cert.
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  await page.goto(DASHBOARD_URL, { waitUntil: "domcontentloaded" });

  // If already logged in (e.g. reused browser state) this form won't exist - skip login.
  const oauthForm = page.locator('form[action="/oauth/start"]');
  if (await oauthForm.count()) {
    await oauthForm.evaluate((f) => f.submit());
    await page.getByRole("link", { name: authType }).last().click();
    await page.locator('input[name="username"]').fill(username);
    await page.locator('input[name="password"]').fill(password);
    await page.locator("form").evaluate((f) => f.submit());
  }

  // Wait for a known post-login dashboard element rather than a fixed sleep.
  await page.waitForSelector("text=Data Science Projects", { timeout: 30000 });

  await page.screenshot({ path: outPath, fullPage: true });
  await browser.close();
  console.log(`Screenshot written to ${outPath}`);
}

const [cmd, outArg] = process.argv.slice(2);
const outPath = outArg || path.join(__dirname, "screenshots", "dashboard.png");

switch (cmd) {
  case "login-screenshot":
    await loginScreenshot(outPath);
    break;
  default:
    console.error("Usage: node driver.mjs login-screenshot [output.png]");
    process.exit(1);
}
