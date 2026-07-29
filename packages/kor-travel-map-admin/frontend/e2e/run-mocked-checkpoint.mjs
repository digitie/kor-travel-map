import { spawn, spawnSync } from "node:child_process";
import { pbkdf2Sync, randomBytes } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { createRequire } from "node:module";
import { connect as connectTcp, isIP } from "node:net";
import os from "node:os";
import path from "node:path";

import { frontendBuildInputs } from "../../../../scripts/frontend-build-inputs.mjs";

const checkpoints = new Set(["A", "B", "C", "D"]);
const [checkpoint, ...playwrightArgs] = process.argv.slice(2);
const repoRoot = path.resolve(process.cwd(), "../../..");
const playwrightEnvironment = {};
for (const name of [
  "CI",
  "HOME",
  "LANG",
  "LC_ALL",
  "LOGNAME",
  "PATH",
  "PLAYWRIGHT_BROWSERS_PATH",
  "SHELL",
  "TEMP",
  "TMP",
  "TMPDIR",
  "TZ",
  "USER",
]) {
  const value = process.env[name];
  if (value !== undefined) playwrightEnvironment[name] = value;
}

if (!checkpoint || !checkpoints.has(checkpoint)) {
  console.error(
    "사용법: npm run e2e:mocked:checkpoint -- <A|B|C|D> [--workers=<양의 정수>]",
  );
  process.exit(2);
}

const unsafeArgs = playwrightArgs.filter(
  (argument) => !/^--workers=[1-9][0-9]*$/.test(argument),
);
if (unsafeArgs.length > 0) {
  console.error(
    "checkpoint는 전체 suite를 보존하는 --workers=<양의 정수> 외 Playwright 인자를 허용하지 않습니다.",
  );
  process.exit(2);
}

const revision = process.env.MOCKED_E2E_REVISION ?? process.env.GITHUB_SHA;
if (!revision || !/^[0-9a-f]{40}$/.test(revision)) {
  console.error(
    "MOCKED_E2E_REVISION 또는 GITHUB_SHA에 exact 40자 SHA가 필요합니다.",
  );
  process.exit(2);
}

const headResult = spawnSync("git", ["rev-parse", "HEAD"], {
  cwd: repoRoot,
  encoding: "utf8",
});
const headRevision = headResult.stdout?.trim();
if (
  headResult.status !== 0 ||
  !headRevision ||
  !/^[0-9a-f]{40}$/.test(headRevision)
) {
  console.error(
    "checkpoint 실행 worktree의 exact Git HEAD를 확인할 수 없습니다.",
  );
  process.exit(2);
}
if (revision !== headRevision) {
  console.error(
    `checkpoint revision이 Git HEAD와 다릅니다: declared=${revision}, head=${headRevision}`,
  );
  process.exit(2);
}
const statusResult = spawnSync(
  "git",
  ["status", "--porcelain", "--untracked-files=normal"],
  {
    cwd: repoRoot,
    encoding: "utf8",
  },
);
if (statusResult.status !== 0 || statusResult.stdout.trim()) {
  console.error(
    "checkpoint는 tracked/untracked 변경이 없는 exact Git worktree에서만 실행할 수 있습니다.",
  );
  process.exit(2);
}

const frontendBaseUrl = process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705";
let parsedBaseUrl;
try {
  parsedBaseUrl = new URL(frontendBaseUrl);
} catch {
  console.error("E2E_BASE_URL에 유효한 loopback HTTP URL이 필요합니다.");
  process.exit(2);
}
const basePort = Number(parsedBaseUrl.port || "80");
if (
  parsedBaseUrl.protocol !== "http:" ||
  parsedBaseUrl.pathname !== "/" ||
  parsedBaseUrl.search ||
  parsedBaseUrl.hash ||
  parsedBaseUrl.username ||
  parsedBaseUrl.password ||
  parsedBaseUrl.hostname !== "127.0.0.1" ||
  !Number.isInteger(basePort) ||
  basePort < 1 ||
  basePort > 65_535
) {
  console.error(
    "E2E_BASE_URL은 경로·인증정보가 없는 127.0.0.1 HTTP URL이어야 합니다.",
  );
  process.exit(2);
}
const isolatedBuildEnvironment = {
  NEXT_PUBLIC_KOR_TRAVEL_MAP_API: "http://127.0.0.1:9",
  NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL: "http://127.0.0.1:9",
  NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL: "http://127.0.0.1:9",
  NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY: "",
  NEXT_PUBLIC_VWORLD_API_KEY: "",
};
const sourceDigestResult = spawnSync(
  process.execPath,
  [path.join(repoRoot, "scripts/frontend-source-digest.mjs")],
  {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...playwrightEnvironment,
      ...isolatedBuildEnvironment,
    },
  },
);
const sourceDigest = sourceDigestResult.stdout?.trim();
if (
  sourceDigestResult.status !== 0 ||
  !sourceDigest ||
  !/^[0-9a-f]{64}$/.test(sourceDigest)
) {
  console.error("현재 frontend source digest를 계산할 수 없습니다.");
  process.exit(2);
}
const adminUsername = process.env.E2E_ADMIN_USERNAME ?? "admin";
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
if (
  !adminPassword ||
  /[\r\n]/.test(adminUsername) ||
  /[\r\n]/.test(adminPassword)
) {
  console.error(
    "self-owned frontend 인증에 줄바꿈 없는 E2E_ADMIN_USERNAME/PASSWORD가 필요합니다.",
  );
  process.exit(2);
}

function base64Url(value) {
  return value.toString("base64url");
}

const passwordSalt = randomBytes(16);
const passwordHash = pbkdf2Sync(
  adminPassword,
  passwordSalt,
  310_000,
  32,
  "sha256",
);
const runtimeDirectory = mkdtempSync(
  path.join(os.tmpdir(), "ktm-mocked-checkpoint-"),
);
const buildContextDirectory = path.join(runtimeDirectory, "build-context");
const buildContextArchive = path.join(runtimeDirectory, "build-context.tar");
const imageIdPath = path.join(runtimeDirectory, "frontend-image.id");
const runtimeEnvPath = path.join(runtimeDirectory, "frontend.env");
const storageStatePath = path.join(runtimeDirectory, "admin-state.json");
const playwrightArtifactRoot = path.join(runtimeDirectory, "playwright");

const ownedContainerName = `ktm-mocked-e2e-${process.pid}-${randomBytes(6).toString("hex")}`;
const ownedNetworkName = `ktm-mocked-e2e-${process.pid}-${randomBytes(6).toString("hex")}-net`;
let ownedContainerId;
let ownedImageTag;
let ownedNetworkId;
let containerCreateAttempted = false;
let networkCreateAttempted = false;
let imageInspect;
let activeChild;
let denyProxyServer;
let frontendProxyServer;
let deniedNetworkAttempts = 0;
let filesystemCleaned = false;
let cleanupPromise;
let cleanupFailed = false;
let terminating = false;

function cleanupFilesystem() {
  if (filesystemCleaned) return;
  filesystemCleaned = true;
  rmSync(runtimeDirectory, { force: true, recursive: true });
}

function runCleanupCommand(args) {
  return new Promise((resolve) => {
    const child = spawn("docker", args, {
      detached: process.platform !== "win32",
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout?.on("data", (chunk) => stdout.push(chunk));
    child.stderr?.on("data", (chunk) => stderr.push(chunk));
    let settled = false;
    const finish = (status = 1) => {
      if (settled) return;
      settled = true;
      clearTimeout(forceTimer);
      resolve({
        status,
        stderr: Buffer.concat(stderr).toString("utf8"),
        stdout: Buffer.concat(stdout).toString("utf8"),
      });
    };
    const forceTimer = setTimeout(() => {
      terminateChildGroup(child, "SIGKILL");
      finish(1);
    }, 1_000);
    child.once("error", () => finish(1));
    child.once("exit", (status) => finish(status ?? 1));
  });
}

async function cleanupOwnedNetwork() {
  if (!networkCreateAttempted) return;
  const inspected = await runCleanupCommand([
    "network",
    "inspect",
    "--format",
    '{{.Id}} {{index .Labels "io.kortravelmap.mocked-e2e-owned"}}',
    ownedNetworkName,
  ]);
  if (inspected.status !== 0) {
    const listed = await runCleanupCommand([
      "network",
      "ls",
      "-q",
      "--filter",
      `name=^${ownedNetworkName}$`,
    ]);
    if (
      listed.status === 0 &&
      listed.stdout.trim() === "" &&
      ownedNetworkId === undefined
    ) {
      return;
    }
    cleanupFailed = true;
    return;
  }
  const [observedId, ownedLabel, ...extra] = inspected.stdout.trim().split(/\s+/);
  if (
    extra.length !== 0 ||
    ownedLabel !== "true" ||
    !/^[0-9a-f]{64}$/.test(observedId ?? "") ||
    (ownedNetworkId !== undefined && observedId !== ownedNetworkId)
  ) {
    cleanupFailed = true;
    return;
  }
  const removed = await runCleanupCommand([
    "network",
    "rm",
    ownedNetworkName,
  ]);
  const postList = await runCleanupCommand([
    "network",
    "ls",
    "-q",
    "--filter",
    `name=^${ownedNetworkName}$`,
  ]);
  if (
    removed.status !== 0 ||
    postList.status !== 0 ||
    postList.stdout.trim() !== ""
  ) {
    cleanupFailed = true;
  }
}

async function cleanupOwnedContainer() {
  if (!containerCreateAttempted) return;
  const inspected = await runCleanupCommand([
    "inspect",
    "--format",
    '{{.Id}} {{index .Config.Labels "io.kortravelmap.mocked-e2e-owned"}}',
    ownedContainerName,
  ]);
  if (inspected.status !== 0) {
    const listed = await runCleanupCommand([
      "ps",
      "-aq",
      "--no-trunc",
      "--filter",
      `name=^${ownedContainerName}$`,
    ]);
    if (
      listed.status === 0 &&
      listed.stdout.trim() === "" &&
      ownedContainerId === undefined
    ) {
      return;
    }
    cleanupFailed = true;
    return;
  }
  const [observedId, ownedLabel, ...extra] = inspected.stdout.trim().split(/\s+/);
  if (
    extra.length !== 0 ||
    ownedLabel !== "true" ||
    !/^[0-9a-f]{64}$/.test(observedId ?? "") ||
    (ownedContainerId !== undefined && observedId !== ownedContainerId)
  ) {
    cleanupFailed = true;
    return;
  }
  const removed = await runCleanupCommand(["rm", "-f", observedId]);
  const listed = await runCleanupCommand([
    "ps",
    "-aq",
    "--no-trunc",
    "--filter",
    `name=^${ownedContainerName}$`,
  ]);
  if (
    removed.status !== 0 ||
    listed.status !== 0 ||
    listed.stdout.trim() !== ""
  ) {
    cleanupFailed = true;
  }
}

async function cleanupOwnedImage() {
  if (!ownedImageTag) return;
  const inspected = await runCleanupCommand([
    "image",
    "inspect",
    "--format",
    "{{.Id}}",
    ownedImageTag,
  ]);
  if (inspected.status !== 0) {
    const listed = await runCleanupCommand([
      "image",
      "ls",
      "-q",
      "--no-trunc",
      ownedImageTag,
    ]);
    if (listed.status === 0 && listed.stdout.trim() === "") return;
    cleanupFailed = true;
    return;
  }
  const observedId = inspected.stdout.trim();
  if (
    !/^sha256:[0-9a-f]{64}$/.test(observedId) ||
    (imageInspect !== undefined && observedId !== imageInspect.Id)
  ) {
    cleanupFailed = true;
    return;
  }
  const removed = await runCleanupCommand([
    "image",
    "rm",
    "-f",
    ownedImageTag,
  ]);
  const listed = await runCleanupCommand([
    "image",
    "ls",
    "-q",
    "--no-trunc",
    ownedImageTag,
  ]);
  if (
    removed.status !== 0 ||
    listed.status !== 0 ||
    listed.stdout.trim() !== ""
  ) {
    cleanupFailed = true;
  }
}

function closeDenyProxy() {
  return new Promise((resolve) => {
    if (!denyProxyServer) {
      resolve();
      return;
    }
    const server = denyProxyServer;
    denyProxyServer = undefined;
    server.close(() => resolve());
    server.closeAllConnections();
  });
}

function closeFrontendProxy() {
  return new Promise((resolve) => {
    if (!frontendProxyServer) {
      resolve();
      return;
    }
    const server = frontendProxyServer;
    frontendProxyServer = undefined;
    server.close(() => resolve());
    server.closeAllConnections();
  });
}

function cleanup() {
  cleanupFilesystem();
  cleanupPromise ??= (async () => {
    await closeDenyProxy();
    await closeFrontendProxy();
    await cleanupOwnedContainer();
    await cleanupOwnedNetwork();
    await cleanupOwnedImage();
  })();
  return cleanupPromise;
}

function startFrontendProxy(targetHost) {
  return new Promise((resolve, reject) => {
    if (isIP(targetHost) !== 4) {
      reject(new Error("frontend internal IPv4 identity가 올바르지 않습니다."));
      return;
    }
    const server = createServer((request, response) => {
      const upstream = httpRequest(
        {
          headers: request.headers,
          host: targetHost,
          method: request.method,
          path: request.url,
          port: basePort,
        },
        (upstreamResponse) => {
          response.writeHead(
            upstreamResponse.statusCode ?? 502,
            upstreamResponse.headers,
          );
          upstreamResponse.pipe(response);
        },
      );
      upstream.on("error", () => {
        if (!response.headersSent) response.writeHead(502);
        response.end();
      });
      request.pipe(upstream);
    });
    server.on("upgrade", (request, socket, head) => {
      const upstream = connectTcp(basePort, targetHost, () => {
        const headers = Object.entries(request.headers)
          .flatMap(([name, value]) =>
            Array.isArray(value)
              ? value.map((item) => `${name}: ${item}`)
              : [`${name}: ${value ?? ""}`],
          )
          .join("\r\n");
        upstream.write(
          `${request.method} ${request.url} HTTP/${request.httpVersion}\r\n${headers}\r\n\r\n`,
        );
        if (head.length > 0) upstream.write(head);
        socket.pipe(upstream).pipe(socket);
      });
      upstream.on("error", () => socket.destroy());
    });
    server.once("error", reject);
    server.listen(basePort, "127.0.0.1", () => {
      frontendProxyServer = server;
      resolve();
    });
  });
}

function startDenyProxy() {
  return new Promise((resolve, reject) => {
    const server = createServer((_request, response) => {
      deniedNetworkAttempts += 1;
      response.writeHead(502, {
        connection: "close",
        "content-type": "text/plain",
      });
      response.end("mocked checkpoint external network denied\n");
    });
    server.on("connect", (_request, socket) => {
      deniedNetworkAttempts += 1;
      socket.end("HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n");
    });
    server.on("upgrade", (_request, socket) => {
      deniedNetworkAttempts += 1;
      socket.end("HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n");
    });
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error("mocked deny proxy의 loopback port를 확인할 수 없습니다."));
        return;
      }
      denyProxyServer = server;
      resolve(`http://127.0.0.1:${address.port}`);
    });
  });
}

function terminateChildGroup(child, signal) {
  try {
    if (process.platform === "win32") {
      child.kill(signal);
    } else {
      process.kill(-child.pid, signal);
    }
  } catch {
    // 이미 종료된 child/process group은 cleanup 완료로 간주한다.
  }
}

async function handleSignal(signal, exitCode) {
  if (terminating) return;
  terminating = true;
  cleanupFilesystem();
  const child = activeChild;
  if (child?.pid) {
    const childExited = new Promise((resolve) => child.once("exit", resolve));
    terminateChildGroup(child, signal);
    const exited = await Promise.race([
      childExited.then(() => true),
      new Promise((resolve) => setTimeout(() => resolve(false), 750)),
    ]);
    if (!exited) {
      terminateChildGroup(child, "SIGKILL");
      await Promise.race([
        childExited,
        new Promise((resolve) => setTimeout(resolve, 750)),
      ]);
    }
  }
  await cleanup();
  process.exit(cleanupFailed ? 2 : exitCode);
}

const signalExitCodes = new Map([
  ["SIGHUP", 129],
  ["SIGINT", 130],
  ["SIGTERM", 143],
]);
for (const [signal, exitCode] of signalExitCodes) {
  process.on(signal, () => {
    void handleSignal(signal, exitCode);
  });
}

function runManagedChild(command, args, options = {}) {
  return new Promise((resolve) => {
    const { captureOutput = false, ...spawnOptions } = options;
    const child = spawn(command, args, {
      ...spawnOptions,
      detached: process.platform !== "win32",
      stdio: captureOutput ? ["ignore", "pipe", "pipe"] : spawnOptions.stdio,
    });
    activeChild = child;
    let stdout = "";
    let stderr = "";
    if (captureOutput) {
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", (chunk) => {
        stdout += chunk;
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk;
      });
    }
    let settled = false;
    child.once("error", (error) => {
      if (settled) return;
      settled = true;
      if (activeChild === child) activeChild = undefined;
      resolve({ error, status: 1, stderr, stdout });
    });
    child.once("exit", (status, signal) => {
      if (settled) return;
      settled = true;
      if (activeChild === child) activeChild = undefined;
      resolve({ signal, status: status ?? 1, stderr, stdout });
    });
  });
}

async function inspectOwnedContainer() {
  const inspectResult = await runManagedChild(
    "docker",
    ["inspect", ownedContainerId],
    { captureOutput: true },
  );
  let inspected;
  try {
    const parsed = JSON.parse(inspectResult.stdout);
    inspected = Array.isArray(parsed) ? parsed.at(0) : undefined;
  } catch {
    inspected = undefined;
  }
  if (
    inspectResult.status !== 0 ||
    !inspected ||
    inspected.Id !== ownedContainerId ||
    inspected.Image !== imageInspect.Id ||
    inspected.State?.Running !== true
  ) {
    throw new Error(
      "runner가 생성한 frontend container의 실행 identity를 확인할 수 없습니다.",
    );
  }
  return inspected;
}

async function inspectBuiltImage(builtImageId) {
  const inspectResult = await runManagedChild(
    "docker",
    ["image", "inspect", builtImageId],
    { captureOutput: true },
  );
  let inspected;
  try {
    const parsed = JSON.parse(inspectResult.stdout);
    inspected = Array.isArray(parsed) ? parsed.at(0) : undefined;
  } catch {
    inspected = undefined;
  }
  if (
    inspectResult.status !== 0 ||
    !inspected ||
    inspected.Id !== builtImageId ||
    inspected.Config?.Labels?.["org.opencontainers.image.revision"] !== revision
  ) {
    throw new Error(
      "self-built frontend immutable image ID/revision label이 checkpoint와 다릅니다.",
    );
  }
  return inspected;
}

function compactDiagnostic(value) {
  return value
    .replace(
      /((?:password|passwd|secret|token|api[_-]?key)[A-Z0-9_]*)=[^\s]+/gi,
      "$1=<redacted>",
    )
    .replace(/[\r\n]+/g, " | ")
    .trim()
    .slice(-2_000);
}

async function frontendReadinessDiagnostic() {
  if (!ownedContainerId) return "container=unavailable";
  const stateResult = await runManagedChild(
    "docker",
    [
      "inspect",
      "--format",
      "{{json .State}}",
      ownedContainerId,
    ],
    { captureOutput: true },
  );
  const logsResult = await runManagedChild(
    "docker",
    ["logs", "--tail", "40", ownedContainerId],
    { captureOutput: true },
  );
  const state =
    stateResult.status === 0
      ? compactDiagnostic(stateResult.stdout)
      : `inspect_exit=${stateResult.status}`;
  const logs = compactDiagnostic(
    `${logsResult.stdout}\n${logsResult.stderr}`,
  );
  return `state=${state || "empty"}; logs=${logs || "empty"}`;
}

async function readBuildInfo(timeoutMs) {
  let lastError = "응답 없음";
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(
        new URL("/api/build-info", frontendBaseUrl),
        {
          headers: { accept: "application/json" },
          signal: AbortSignal.timeout(Math.min(2_000, timeoutMs)),
        },
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      const observedRevision =
        typeof payload === "object" &&
        payload !== null &&
        "revision" in payload &&
        typeof payload.revision === "string"
          ? payload.revision
          : undefined;
      const observedSourceDigest =
        typeof payload === "object" &&
        payload !== null &&
        "source_digest" in payload &&
        typeof payload.source_digest === "string"
          ? payload.source_digest
          : undefined;
      if (observedRevision && observedSourceDigest) {
        return {
          revision: observedRevision,
          sourceDigest: observedSourceDigest,
        };
      }
      lastError = "필수 필드 없음";
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const diagnostic = await frontendReadinessDiagnostic();
  throw new Error(
    `self-owned frontend build-info를 확인할 수 없습니다: ${lastError}; ${diagnostic}`,
  );
}

let exitCode = 2;
try {
  const archiveResult = await runManagedChild(
    "git",
    ["archive", "--format=tar", `--output=${buildContextArchive}`, "HEAD"],
    { captureOutput: true, cwd: repoRoot },
  );
  if (archiveResult.status !== 0) {
    throw new Error("exact HEAD build context archive를 만들 수 없습니다.");
  }
  const mkdirResult = await runManagedChild(
    "mkdir",
    ["-p", buildContextDirectory],
    {
      captureOutput: true,
    },
  );
  const extractResult = await runManagedChild(
    "tar",
    ["-xf", buildContextArchive, "-C", buildContextDirectory],
    {
      captureOutput: true,
    },
  );
  if (mkdirResult.status !== 0 || extractResult.status !== 0) {
    throw new Error("exact HEAD build context archive를 펼칠 수 없습니다.");
  }
  ownedImageTag =
    `kor-travel-map-mocked-e2e:${revision.slice(0, 12)}-` +
    `${process.pid}-${randomBytes(6).toString("hex")}`;
  const publicBuildArgs = frontendBuildInputs(isolatedBuildEnvironment).flatMap(
    ([name, value]) => ["--build-arg", `${name}=${value}`],
  );
  const buildResult = await runManagedChild(
    "docker",
    [
      "build",
      "--iidfile",
      imageIdPath,
      "--build-arg",
      `KOR_TRAVEL_MAP_GIT_COMMIT=${revision}`,
      ...publicBuildArgs,
      "-f",
      path.join(buildContextDirectory, "docker/frontend.Dockerfile"),
      "-t",
      ownedImageTag,
      buildContextDirectory,
    ],
    { stdio: "inherit" },
  );
  if (buildResult.error || buildResult.status !== 0) {
    throw new Error("exact HEAD frontend image를 빌드할 수 없습니다.");
  }
  const builtImageId = readFileSync(imageIdPath, "utf8").trim();
  if (!/^sha256:[0-9a-f]{64}$/.test(builtImageId)) {
    throw new Error(
      "빌드한 frontend image의 immutable ID를 확인할 수 없습니다.",
    );
  }
  imageInspect = await inspectBuiltImage(builtImageId);
  writeFileSync(
    runtimeEnvPath,
    [
      `PORT=${basePort}`,
      `KOR_TRAVEL_MAP_UI_ADMIN_USERNAME=${adminUsername}`,
      `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH=pbkdf2_sha256$310000$${base64Url(passwordSalt)}$${base64Url(passwordHash)}`,
      `KOR_TRAVEL_MAP_UI_SESSION_SECRET=${base64Url(randomBytes(32))}`,
      `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=${base64Url(randomBytes(32))}`,
      "KOR_TRAVEL_MAP_API_INTERNAL_URL=http://127.0.0.1:9",
      "HOSTNAME=0.0.0.0",
      "",
    ].join("\n"),
    { encoding: "utf8", mode: 0o600 },
  );
  networkCreateAttempted = true;
  const networkResult = await runManagedChild(
    "docker",
    [
      "network",
      "create",
      "--internal",
      "--label",
      "io.kortravelmap.mocked-e2e-owned=true",
      ownedNetworkName,
    ],
    { captureOutput: true },
  );
  const createdNetworkId = networkResult.stdout?.trim();
  if (
    networkResult.status !== 0 ||
    !createdNetworkId ||
    !/^[0-9a-f]{64}$/.test(createdNetworkId)
  ) {
    throw new Error("self-owned mocked internal network를 생성할 수 없습니다.");
  }
  ownedNetworkId = createdNetworkId;
  containerCreateAttempted = true;
  const createResult = await runManagedChild(
    "docker",
    [
      "create",
      "--name",
      ownedContainerName,
      "--label",
      "io.kortravelmap.mocked-e2e-owned=true",
      "--network",
      ownedNetworkName,
      "--read-only",
      "--cap-drop",
      "ALL",
      "--security-opt",
      "no-new-privileges:true",
      "--tmpfs",
      "/tmp:rw,noexec,nosuid,nodev,size=64m",
      "--env-file",
      runtimeEnvPath,
      imageInspect.Id,
    ],
    { captureOutput: true },
  );
  rmSync(runtimeEnvPath, { force: true });
  ownedContainerId = createResult.stdout?.trim();
  if (
    createResult.status !== 0 ||
    !ownedContainerId ||
    !/^[0-9a-f]{64}$/.test(ownedContainerId)
  ) {
    throw new Error("self-owned frontend container를 생성할 수 없습니다.");
  }
  const startResult = await runManagedChild(
    "docker",
    ["start", ownedContainerId],
    { captureOutput: true },
  );
  if (startResult.status !== 0) {
    throw new Error("self-owned frontend container를 시작할 수 없습니다.");
  }
  const containerInspect = await inspectOwnedContainer();
  const frontendContainerIp =
    containerInspect.NetworkSettings?.Networks?.[ownedNetworkName]?.IPAddress;
  if (!frontendContainerIp || isIP(frontendContainerIp) !== 4) {
    throw new Error("self-owned frontend internal IPv4 identity를 확인할 수 없습니다.");
  }
  await startFrontendProxy(frontendContainerIp);
  const frontendBuildInfo = await readBuildInfo(30_000);
  if (frontendBuildInfo.revision !== revision) {
    throw new Error(
      `실제 frontend revision이 checkpoint와 다릅니다: declared=${revision}, frontend=${frontendBuildInfo.revision}`,
    );
  }
  if (frontendBuildInfo.sourceDigest !== sourceDigest) {
    throw new Error(
      `실제 frontend source digest가 checkpoint worktree와 다릅니다: expected=${sourceDigest}, frontend=${frontendBuildInfo.sourceDigest}`,
    );
  }

  const require = createRequire(import.meta.url);
  const playwrightCli = require.resolve("@playwright/test/cli");
  const denyProxyUrl = await startDenyProxy();
  const result = await runManagedChild(
    process.execPath,
    [
      playwrightCli,
      "test",
      ...playwrightArgs,
      "--reporter=list,./e2e/mocked-failure-reporter.ts",
    ],
    {
      env: {
        ...playwrightEnvironment,
        MOCKED_E2E_CHECKPOINT: checkpoint,
        MOCKED_E2E_REVISION: revision,
        MOCKED_E2E_VERIFIED_REVISION: headRevision,
        MOCKED_E2E_VERIFIED_FRONTEND_REVISION: frontendBuildInfo.revision,
        MOCKED_E2E_VERIFIED_FRONTEND_SOURCE_DIGEST:
          frontendBuildInfo.sourceDigest,
        MOCKED_E2E_VERIFIED_FRONTEND_IMAGE_ID: imageInspect.Id,
        MOCKED_E2E_VERIFIED_FRONTEND_CONTAINER_ID: containerInspect.Id,
        MOCKED_E2E_ALLOWED_ORIGIN: parsedBaseUrl.origin,
        MOCKED_E2E_DENY_PROXY: denyProxyUrl,
        E2E_ADMIN_USERNAME: adminUsername,
        E2E_ADMIN_PASSWORD: adminPassword,
        E2E_BASE_URL: parsedBaseUrl.origin,
        NEXT_PUBLIC_KOR_TRAVEL_MAP_API: "http://127.0.0.1:9",
        NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL: "http://127.0.0.1:9",
        NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL: "http://127.0.0.1:9",
        NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY: "",
        NEXT_PUBLIC_VWORLD_API_KEY: "",
        E2E_STORAGE_STATE: storageStatePath,
        PLAYWRIGHT_ARTIFACT_ROOT: playwrightArtifactRoot,
      },
      stdio: "inherit",
    },
  );
  const postHeadResult = await runManagedChild(
    "git",
    ["rev-parse", "HEAD"],
    { captureOutput: true, cwd: repoRoot },
  );
  const postStatusResult = await runManagedChild(
    "git",
    ["status", "--porcelain", "--untracked-files=normal"],
    { captureOutput: true, cwd: repoRoot },
  );
  const postSourceDigestResult = await runManagedChild(
    process.execPath,
    [path.join(repoRoot, "scripts/frontend-source-digest.mjs")],
    {
      captureOutput: true,
      cwd: repoRoot,
      env: {
        ...playwrightEnvironment,
        ...isolatedBuildEnvironment,
      },
    },
  );
  if (
    postHeadResult.status !== 0 ||
    postHeadResult.stdout.trim() !== headRevision ||
    postStatusResult.status !== 0 ||
    postStatusResult.stdout.trim() ||
    postSourceDigestResult.status !== 0 ||
    postSourceDigestResult.stdout.trim() !== sourceDigest
  ) {
    throw new Error(
      "mocked E2E 실행 전후 worktree HEAD/status/source digest가 달라졌습니다.",
    );
  }
  const postContainerInspect = await inspectOwnedContainer();
  const postBuildInfo = await readBuildInfo(5_000);
  if (
    postContainerInspect.Id !== containerInspect.Id ||
    postBuildInfo.revision !== frontendBuildInfo.revision ||
    postBuildInfo.sourceDigest !== frontendBuildInfo.sourceDigest
  ) {
    throw new Error(
      "mocked E2E 실행 전후 frontend container/build identity가 달라졌습니다.",
    );
  }
  if (deniedNetworkAttempts !== 0) {
    throw new Error(
      "mocked E2E가 self-owned frontend 밖의 HTTP/WebSocket 연결을 시도했습니다.",
    );
  }
  if (result.error) {
    console.error(result.error.message);
    exitCode = 1;
  } else {
    exitCode = result.status ?? 1;
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  exitCode = 2;
} finally {
  await cleanup();
}
if (cleanupFailed) exitCode = 2;
process.exit(exitCode);
