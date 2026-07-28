import { spawn, spawnSync } from "node:child_process";
import { pbkdf2Sync, randomBytes } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

import { frontendBuildInputs } from "../../../../scripts/frontend-build-inputs.mjs";

const checkpoints = new Set(["A", "B", "C", "D"]);
const [checkpoint, ...playwrightArgs] = process.argv.slice(2);
const repoRoot = path.resolve(process.cwd(), "../../..");

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
const sourceDigestResult = spawnSync(
  process.execPath,
  [path.join(repoRoot, "scripts/frontend-source-digest.mjs")],
  {
    cwd: repoRoot,
    encoding: "utf8",
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

const ownedContainerName = `ktm-mocked-e2e-${process.pid}-${randomBytes(6).toString("hex")}`;
let ownedContainerId;
let imageInspect;
let activeChild;
let cleaned = false;
let terminating = false;
function cleanup() {
  if (cleaned) return;
  cleaned = true;
  if (ownedContainerId) {
    spawnSync("docker", ["rm", "-f", ownedContainerId], {
      stdio: "ignore",
    });
  }
  rmSync(runtimeDirectory, { force: true, recursive: true });
}
const signalExitCodes = new Map([
  ["SIGHUP", 129],
  ["SIGINT", 130],
  ["SIGTERM", 143],
]);
for (const [signal, exitCode] of signalExitCodes) {
  process.once(signal, () => {
    if (terminating) return;
    terminating = true;
    if (!activeChild?.pid) {
      cleanup();
      process.exit(exitCode);
    }
    const terminateChildGroup = (childSignal) => {
      try {
        if (process.platform === "win32") {
          activeChild.kill(childSignal);
        } else {
          process.kill(-activeChild.pid, childSignal);
        }
      } catch {
        // 이미 종료된 child/process group은 cleanup 완료로 간주한다.
      }
    };
    terminateChildGroup(signal);
    cleanup();
    const forceTimer = setTimeout(() => {
      terminateChildGroup("SIGKILL");
      process.exit(exitCode);
    }, 5_000);
    forceTimer.unref();
    activeChild.once("exit", () => {
      clearTimeout(forceTimer);
      process.exit(exitCode);
    });
  });
}

function runManagedChild(command, args, options = {}) {
  return new Promise((resolve) => {
    activeChild = spawn(command, args, {
      ...options,
      detached: process.platform !== "win32",
    });
    let settled = false;
    activeChild.once("error", (error) => {
      if (settled) return;
      settled = true;
      activeChild = undefined;
      resolve({ error, status: 1 });
    });
    activeChild.once("exit", (status, signal) => {
      if (settled) return;
      settled = true;
      activeChild = undefined;
      resolve({ signal, status: status ?? 1 });
    });
  });
}

function inspectOwnedContainer() {
  const inspectResult = spawnSync("docker", ["inspect", ownedContainerId], {
    encoding: "utf8",
  });
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
  throw new Error(
    `self-owned frontend build-info를 확인할 수 없습니다: ${lastError}`,
  );
}

let exitCode = 2;
try {
  const archiveResult = spawnSync(
    "git",
    ["archive", "--format=tar", `--output=${buildContextArchive}`, "HEAD"],
    { cwd: repoRoot, encoding: "utf8" },
  );
  if (archiveResult.status !== 0) {
    throw new Error("exact HEAD build context archive를 만들 수 없습니다.");
  }
  const mkdirResult = spawnSync("mkdir", ["-p", buildContextDirectory], {
    encoding: "utf8",
  });
  const extractResult = spawnSync(
    "tar",
    ["-xf", buildContextArchive, "-C", buildContextDirectory],
    { encoding: "utf8" },
  );
  if (mkdirResult.status !== 0 || extractResult.status !== 0) {
    throw new Error("exact HEAD build context archive를 펼칠 수 없습니다.");
  }
  const ownedImageTag = `kor-travel-map-mocked-e2e:${revision.slice(0, 12)}`;
  const publicBuildArgs = frontendBuildInputs().flatMap(([name, value]) => [
    "--build-arg",
    `${name}=${value}`,
  ]);
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
  const imageInspectResult = spawnSync(
    "docker",
    ["image", "inspect", builtImageId],
    { encoding: "utf8" },
  );
  try {
    const parsed = JSON.parse(imageInspectResult.stdout);
    imageInspect = Array.isArray(parsed) ? parsed.at(0) : undefined;
  } catch {
    imageInspect = undefined;
  }
  if (
    imageInspectResult.status !== 0 ||
    !imageInspect ||
    imageInspect.Id !== builtImageId ||
    imageInspect.Config?.Labels?.["org.opencontainers.image.revision"] !==
      revision
  ) {
    throw new Error(
      "self-built frontend immutable image ID/revision label이 checkpoint와 다릅니다.",
    );
  }
  writeFileSync(
    runtimeEnvPath,
    [
      `PORT=${basePort}`,
      `KOR_TRAVEL_MAP_UI_ADMIN_USERNAME=${adminUsername}`,
      `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH=pbkdf2_sha256$310000$${base64Url(passwordSalt)}$${base64Url(passwordHash)}`,
      `KOR_TRAVEL_MAP_UI_SESSION_SECRET=${base64Url(randomBytes(32))}`,
      `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=${base64Url(randomBytes(32))}`,
      "KOR_TRAVEL_MAP_API_INTERNAL_URL=http://127.0.0.1:9",
      "",
    ].join("\n"),
    { encoding: "utf8", mode: 0o600 },
  );
  const createResult = spawnSync(
    "docker",
    [
      "create",
      "--name",
      ownedContainerName,
      "--network",
      "host",
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
    { encoding: "utf8" },
  );
  ownedContainerId = createResult.stdout?.trim();
  if (
    createResult.status !== 0 ||
    !ownedContainerId ||
    !/^[0-9a-f]{64}$/.test(ownedContainerId)
  ) {
    throw new Error("self-owned frontend container를 생성할 수 없습니다.");
  }
  const startResult = spawnSync("docker", ["start", ownedContainerId], {
    encoding: "utf8",
  });
  if (startResult.status !== 0) {
    throw new Error("self-owned frontend container를 시작할 수 없습니다.");
  }
  const containerInspect = inspectOwnedContainer();
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
        ...process.env,
        MOCKED_E2E_CHECKPOINT: checkpoint,
        MOCKED_E2E_REVISION: revision,
        MOCKED_E2E_VERIFIED_REVISION: headRevision,
        MOCKED_E2E_VERIFIED_FRONTEND_REVISION: frontendBuildInfo.revision,
        MOCKED_E2E_VERIFIED_FRONTEND_SOURCE_DIGEST:
          frontendBuildInfo.sourceDigest,
        MOCKED_E2E_VERIFIED_FRONTEND_IMAGE_ID: imageInspect.Id,
        MOCKED_E2E_VERIFIED_FRONTEND_CONTAINER_ID: containerInspect.Id,
      },
      stdio: "inherit",
    },
  );
  const postHeadResult = spawnSync("git", ["rev-parse", "HEAD"], {
    cwd: repoRoot,
    encoding: "utf8",
  });
  const postStatusResult = spawnSync(
    "git",
    ["status", "--porcelain", "--untracked-files=normal"],
    { cwd: repoRoot, encoding: "utf8" },
  );
  const postSourceDigestResult = spawnSync(
    process.execPath,
    [path.join(repoRoot, "scripts/frontend-source-digest.mjs")],
    {
      cwd: repoRoot,
      encoding: "utf8",
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
  const postContainerInspect = inspectOwnedContainer();
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
  cleanup();
}
process.exit(exitCode);
