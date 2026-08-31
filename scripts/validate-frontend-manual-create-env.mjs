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

// dotenv-expand는 값 안의 `$`를 변수참조로 확장한다 — 홑따옴표로도 보호되지 않으므로
// `pbkdf2_sha256$…` hash가 dotenv file에 있으면 조용히 파괴돼 로그인이 전부 401이
// 된다(값을 `\$`로 이스케이프해야 한다). 파괴된 결과는 여기서 fail-closed로 잡는다.
const ADMIN_HASH_KEY = "KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH";
const adminPasswordHash = loaded.combinedEnv[ADMIN_HASH_KEY];
if (adminPasswordHash !== undefined && adminPasswordHash.trim() !== "") {
  const shape = /^pbkdf2_sha256\$\d+\$[A-Za-z0-9_-]+\$[A-Za-z0-9_-]+$/;
  const iterations = Number(adminPasswordHash.trim().split("$")[1]);
  if (!shape.test(adminPasswordHash.trim()) || !(iterations >= 100000)) {
    process.stderr.write(
      `${ADMIN_HASH_KEY} is not a valid pbkdf2_sha256 hash after Next dotenv ` +
        "expansion; escape every `$` in the dotenv value as `\\$` " +
        "(single quotes do NOT prevent expansion), or pass the hash via " +
        "process environment\n",
    );
    process.exit(1);
  }
}
