#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const { loadEnvConfig } = require("@next/env");

const API_ONLY_KEYS = new Set([
  "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256",
  "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED",
]);

if (process.argv.length !== 3) {
  process.stderr.write(
    "usage: validate-frontend-manual-create-env.mjs <frontend-directory>\n",
  );
  process.exit(2);
}

const frontendDirectory = resolve(process.argv[2]);
const credentialInput = readFileSync(0, "utf8").split("\0");
if (credentialInput.at(-1) === "") {
  credentialInput.pop();
}
if (credentialInput.length < 2) {
  process.stderr.write("manual Feature create credential input is invalid\n");
  process.exit(2);
}
const [manualCreateRaw, manualCreateDigest, ...frontendProcessEntries] =
  credentialInput;
for (const entry of frontendProcessEntries) {
  const separator = entry.indexOf("=");
  if (separator <= 0) {
    process.stderr.write("frontend process environment input is invalid\n");
    process.exit(2);
  }
  process.env[entry.slice(0, separator)] = entry.slice(separator + 1);
}
if (manualCreateRaw !== "") {
  process.env.KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN = manualCreateRaw;
}
const silentLog = {
  info() {},
  error() {
    process.stderr.write("failed to parse frontend dotenv files\n");
  },
};

let loaded;
try {
  loaded = loadEnvConfig(frontendDirectory, true, silentLog, true);
} catch {
  process.stderr.write("failed to parse frontend dotenv files\n");
  process.exit(1);
}

for (const envFile of loaded.loadedEnvFiles) {
  for (const key of API_ONLY_KEYS) {
    if (Object.hasOwn(envFile.env, key)) {
      process.stderr.write(`API-only key is not allowed in frontend env: ${key}\n`);
      process.exit(1);
    }
  }
}

const effectiveManualCreateRaw =
  loaded.combinedEnv.KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN ?? "";
if (effectiveManualCreateRaw !== "" || manualCreateDigest !== "") {
  for (const [key, value] of Object.entries(loaded.combinedEnv)) {
    if (key === "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN") {
      continue;
    }
    if (
      ((effectiveManualCreateRaw !== "" &&
        value?.includes(effectiveManualCreateRaw)) ||
        (manualCreateDigest !== "" && value?.includes(manualCreateDigest)))
    ) {
      process.stderr.write(
        key.startsWith("NEXT_PUBLIC_")
          ? "manual Feature create credentials must be distinct from public frontend values\n"
          : "manual Feature create credentials are not allowed in frontend runtime aliases\n",
      );
      process.exit(1);
    }
  }
}
