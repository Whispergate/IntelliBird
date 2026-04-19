#!/usr/bin/env node
// web/scripts/openapi-check.mjs
// Drift gate: regenerate api-client.generated.ts and fail if it differs from the committed copy.
// Usage (CI / inside web container): pnpm gen:api:check
// Usage (host dev with stack up): BACKEND_URL=http://localhost:8000 pnpm gen:api:check
// Prereq: docker compose up -d api db redis (backend must be reachable at http://api:8000 or override via BACKEND_URL env)

import { execSync } from "node:child_process";

const backendUrl = process.env.BACKEND_URL ?? "http://api:8000";
const GENERATE_CMD = `node node_modules/openapi-typescript/bin/cli.js ${backendUrl}/openapi.json -o app/api-client.generated.ts`;
const DIFF_CMD = "git diff --exit-code app/api-client.generated.ts";

console.log(
  `Regenerating app/api-client.generated.ts from ${backendUrl}/openapi.json — requires docker compose up -d api`
);

try {
  execSync(GENERATE_CMD, { stdio: "inherit" });
} catch (err) {
  console.error(
    `ERROR: backend not reachable at ${backendUrl} — run 'docker compose -f ops/docker-compose.yml up -d api db redis' first`
  );
  process.exit(1);
}

try {
  execSync(DIFF_CMD, { stdio: "inherit" });
  console.log("OpenAPI drift gate: no drift.");
  process.exit(0);
} catch {
  console.error("OpenAPI drift detected — run `pnpm gen:api` and commit the result.");
  process.exit(1);
}
