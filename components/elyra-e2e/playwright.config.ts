import { defineConfig, devices } from '@playwright/test';

// require.extensions[".css"] = () => ({});
import babel from '@babel/register';
import path from "path";

// https://github.com/tleunen/babel-plugin-module-resolver/issues/336

// this will install a babel hook to node.js so that
// it will process every file as it is being imported

// require.extensions[".css"] = () => ({});
babel()
babel({
  // this is useful for debugging, in effect it logs everything imported
  // that is matching the `extensions` pattern below
  ignore: [
    file => {
      console.log('IGNORE?', file)
      return false
    }
  ],
  extensions: ['.ts'],
  presets: [
    ["@babel/preset-env", {
      "targets": { "node": "current" },
      "modules": "auto"
    }],
    "@babel/preset-typescript"
  ],
  plugins: ["@babel/plugin-transform-runtime",
    ['module-resolver',
    {
      cwd: 'babelrc', // use the local babel.config.js in each project
      root: ['./'],
      alias: {"~": path.resolve(__dirname, "./node_modules/odh-dashboard-frontend/frontend/src/")},
      //resolvePath: "./node_modules/odh-dashboard-frontend/frontend/src/",
    }],
  ],
  include: [
    "**/*"
  ],
});
// require.extensions[".css"] = () => ({});

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  // https://github.com/microsoft/playwright/issues/9702#issuecomment-950010347
  reporter: process.env.CI ? [ ['html', { open: 'never' }] ] : 'line',
  use: {
    baseURL: process.env.BASE_URL || 'https://rhods-dashboard-redhat-ods-applications.apps.ods-qe-ibm-01.ibm.rh-ods.com/',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  // Add Babel preprocessing
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], headless: false, },

    },
    // {
    //   name: 'firefox',
    //   use: { ...devices['Desktop Firefox'] },
    // },
    // {
    //   name: 'webkit',
    //   use: { ...devices['Desktop Safari'] },
    // },
  ],
});