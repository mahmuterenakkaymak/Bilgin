// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { defineConfig } from "vitest/config";

// Built into the package FastAPI serves (config.STATIC_DIR); the dev server proxies the API of `serve`.
export default defineConfig({
  base: "/",
  build: {
    outDir: "../nl2sql/web/static",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8777",
    },
  },
  test: {
    environment: "node",
    // Every test file starts with both catalogs registered, so a render without a provider stays Turkish.
    setupFiles: ["src/test-setup.js"],
  },
});
