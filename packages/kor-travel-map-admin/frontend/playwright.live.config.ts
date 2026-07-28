import { defineConfig, devices } from "@playwright/test";
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";

import { LIVE_STORAGE_STATE } from "./e2e/_auth-state";

const artifactRoot =
  process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
  path.join(os.tmpdir(), "kor-travel-map-playwright", "admin-frontend-live");
const c7RawOutputDir = path.join(
  "/tmp",
  `kor-travel-map-c7-test-results-${process.pid}`,
);

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705";
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const C7_READ_AUTH_SPEC = "ops-c7-read-auth.live.spec";
const ISOLATED_EVIDENCE_ENV = "E2E_ISOLATED_LIVE_EVIDENCE";
const ISOLATED_DOCKER_NETWORK_ENV = "E2E_ISOLATED_LIVE_DOCKER_NETWORK";
const ADMIN_FEATURE_RUN_ID_ENV = "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID";
const ADMIN_FEATURE_RECOVERY_ENV =
  "E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY";
const ADMIN_FEATURE_RUN_ID_PATTERN = /^[a-z0-9][a-z0-9-]{15,79}$/;
const isolatedEvidenceRaw = process.env[ISOLATED_EVIDENCE_ENV];
const isolatedEvidence = isolatedEvidenceRaw === "1";
const isolatedDockerNetworkRaw = process.env[ISOLATED_DOCKER_NETWORK_ENV];
const isolatedDockerNetwork = isolatedDockerNetworkRaw === "1";

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function isC7ReadAuthRun(): boolean {
  return process.argv.some((argument) => argument.includes(C7_READ_AUTH_SPEC));
}

function shouldAssertC7OriginGuard(): boolean {
  return (
    isC7ReadAuthRun() ||
    process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256 !== undefined ||
    process.env.E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256 !== undefined
  );
}

function expectedSha256(envName: string): string {
  const value = process.env[envName];
  if (!value || !SHA256_PATTERN.test(value)) {
    throw new Error(
      `[playwright.live] ${envName}은 lowercase SHA256이어야 합니다 (value redacted)`,
    );
  }
  return value;
}

function isolatedAuthRequestHeaders(): Record<string, string> {
  const runId = process.env[ADMIN_FEATURE_RUN_ID_ENV];
  if (runId === undefined) {
    return {};
  }
  if (
    !isolatedEvidence ||
    !isolatedDockerNetwork ||
    !ADMIN_FEATURE_RUN_ID_PATTERN.test(runId)
  ) {
    throw new Error(
      `[playwright.live] ${ADMIN_FEATURE_RUN_ID_ENV}은 검증된 격리 실행의 run ID여야 합니다`,
    );
  }
  const recoveryRaw = process.env[ADMIN_FEATURE_RECOVERY_ENV];
  if (recoveryRaw !== undefined && recoveryRaw !== "1") {
    throw new Error(
      `[playwright.live] ${ADMIN_FEATURE_RECOVERY_ENV}=1만 허용합니다`,
    );
  }
  const phase = recoveryRaw === "1" ? "recovery" : "main";
  return {
    "x-request-id": `e2e_live_acceptance::${runId}::auth::${phase}`,
  };
}

/**
 * `E2E_LIVE_WORKERS` 검증: 미설정이면 기본 4, 설정됐으면 1 이상의 정수만 허용한다.
 * 빈 문자열/garbage는 `Number()`가 NaN/0으로 조용히 무너뜨리지 않고 config 평가
 * 시점에 명확한 오류로 실행을 막는다(값은 redact).
 */
function liveWorkers(): number {
  const raw = process.env.E2E_LIVE_WORKERS;
  if (raw === undefined) {
    return 4;
  }
  if (!/^[0-9]+$/.test(raw) || Number(raw) < 1) {
    throw new Error(
      "[playwright.live] E2E_LIVE_WORKERS는 1 이상의 정수여야 합니다 (value redacted)",
    );
  }
  return Number(raw);
}

/**
 * prod-target 가드 (#501): live config은 baseURL을 `E2E_BASE_URL`로 자유롭게
 * override할 수 있어, 실수로 prod(map.<domain>) 같은 비-로컬 호스트를 가리킨 채
 * admin UI/API 시나리오 taxonomy와 opt-in 실제 write flow를 돌릴 위험이 있다.
 * 비-로컬 대상은 의도 확인을 위해 `E2E_LIVE_ALLOW_PROD=1` 명시 opt-in 없이는
 * config 평가 시점에 throw해 실행을 막는다.
 */
function isLocalHost(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname === "0.0.0.0" ||
    hostname.endsWith(".localhost")
  );
}

function isTrustedIsolatedDockerOrigin(url: URL): boolean {
  return (
    isolatedDockerNetwork &&
    url.protocol === "http:" &&
    url.hostname === "candidate-ui" &&
    url.username === "" &&
    url.password === "" &&
    url.pathname === "/" &&
    url.search === "" &&
    url.hash === ""
  );
}

(function assertNotProdUnlessOptedIn() {
  let parsed: URL;
  try {
    parsed = new URL(baseURL);
  } catch {
    throw new Error(
      "[playwright.live] E2E_BASE_URL이 유효한 URL이 아닙니다 (value redacted)",
    );
  }
  if (isolatedEvidenceRaw !== undefined && isolatedEvidenceRaw !== "1") {
    throw new Error(
      `[playwright.live] ${ISOLATED_EVIDENCE_ENV}=1만 허용합니다 (value redacted)`,
    );
  }
  if (
    isolatedDockerNetworkRaw !== undefined &&
    isolatedDockerNetworkRaw !== "1"
  ) {
    throw new Error(
      `[playwright.live] ${ISOLATED_DOCKER_NETWORK_ENV}=1만 허용합니다 (value redacted)`,
    );
  }
  if (isolatedDockerNetwork && !isolatedEvidence) {
    throw new Error(
      `[playwright.live] ${ISOLATED_DOCKER_NETWORK_ENV}=1은 ${ISOLATED_EVIDENCE_ENV}=1이 필요합니다`,
    );
  }
  const isolatedTarget =
    isLocalHost(parsed.hostname) || isTrustedIsolatedDockerOrigin(parsed);
  if (isolatedEvidence && !isolatedTarget) {
    throw new Error(
      `[playwright.live] ${ISOLATED_EVIDENCE_ENV}=1은 검증된 격리 대상만 허용합니다`,
    );
  }
  if (!isolatedTarget && process.env.E2E_LIVE_ALLOW_PROD !== "1") {
    throw new Error(
      "[playwright.live] E2E_BASE_URL이 비-로컬(prod 등)입니다 (value redacted). " +
        "의도한 실행이면 E2E_LIVE_ALLOW_PROD=1을 설정하세요.",
    );
  }

  // C7 read/auth origin guard는 project/webServer 생성 전 config 평가에서 끝낸다.
  // UI origin만 여기서 실제 값과 대조하고, API WSS origin은 browser tracer가 실제
  // socket에서 관측한 값을 별도 expected hash와 대조한다.
  if (shouldAssertC7OriginGuard()) {
    if (
      parsed.protocol !== "https:" ||
      parsed.username ||
      parsed.password ||
      parsed.pathname !== "/" ||
      parsed.search ||
      parsed.hash
    ) {
      throw new Error(
        "[playwright.live] C7 E2E_BASE_URL은 공개 HTTPS origin이어야 합니다 (value redacted)",
      );
    }
    const expectedUi = expectedSha256("E2E_C7_EXPECTED_UI_ORIGIN_SHA256");
    expectedSha256("E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256");
    if (sha256(parsed.origin) !== expectedUi) {
      throw new Error(
        "[playwright.live] C7 expected UI origin guard 불일치 (values redacted)",
      );
    }
  }
})();

const redactedEvidence = shouldAssertC7OriginGuard() || isolatedEvidence;
const authRequestHeaders = isolatedAuthRequestHeaders();

/**
 * Playwright e2e — **LIVE(비-mock) 시나리오 전용** config (`e2e/live/**`).
 * WSL에서는 실행하지 않는다. live UI e2e는 n150 Linux가 1순위이고,
 * n150에서 실행할 수 없을 때만 Windows 호스트 브라우저로 fallback한다.
 *
 * 기본 config(playwright.config.ts)는 mock suite로 `e2e/live/**`를 testIgnore한다.
 * 본 config는 라이브 배포 대상(prod 등)에 실데이터로 admin UI/API 시나리오를
 * 돌린다. `admin-scenario-catalog.ts`는 실행 커버리지 수치가 아니라 route/API/
 * reflection 조합을 열거하는 surface taxonomy이고, 대표 route smoke만 이 catalog의
 * live_smoke 항목을 실제 네비게이션으로 돈다. 실제 mutation spec은
 * `E2E_ADMIN_FEATURES_WRITE=1`, `E2E_SETTINGS_WRITE=1` 또는 공통
 * `E2E_ADMIN_WRITE=1` opt-in이 있을 때만 실행한다. 백업/restore처럼 blast radius가
 * 큰 실행은 별도 `E2E_BACKUP_RESTORE_EXECUTE*` opt-in으로 제한한다. 데이터/뷰는
 * `e2e/live/_fixtures.ts`(prod 스냅샷)에서 온다 —
 * fixtures는 배포의 실 API에서 재생성 가능(원본 스크립트는 PR 설명 참조).
 *
 * 실행(로컬 기본 — http://127.0.0.1:12705):
 *   npm run e2e:live
 *
 * worker 수는 `E2E_LIVE_WORKERS`(기본 4)로 조정한다. 비-로컬(prod 등) 대상은 실수
 * 방지를 위해 `E2E_LIVE_ALLOW_PROD=1` 명시 opt-in이 필요하다(아래 가드 참고):
 *   E2E_LIVE_ALLOW_PROD=1 E2E_LIVE_WORKERS=4 E2E_ADMIN_PASSWORD=<admin-pw> \
 *     E2E_C7_EXPECTED_UI_ORIGIN_SHA256=<sha256> \
 *     E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256=<sha256> \
 *     E2E_BASE_URL=https://map.<domain> E2E_DAGSTER_URL=https://map-dagster.<domain> \
 *     npm run e2e:live -- --retries=1
 *
 * #520 인증 게이트: `E2E_ADMIN_PASSWORD`(+ 선택 `E2E_ADMIN_USERNAME`, 기본 admin)를 주면
 * auth.setup이 로그인 세션을 만들어 모든 spec이 인증 상태로 돈다(미설정 시 인증 미적용 대상으로 간주).
 *
 * CI에서는 돌리지 않는다(라이브 배포 + 실데이터 필요 — admin e2e는 CI job 없음).
 */
export default defineConfig({
  testDir: "./e2e/live",
  globalTeardown: "./e2e/live/global-teardown.ts",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  // C7의 raw attachment/error output은 evidence bind 밖 container tmpfs에만 둔다.
  outputDir: redactedEvidence
    ? c7RawOutputDir
    : path.join(artifactRoot, "test-results"),
  fullyParallel: true,
  // worker 상한(#501): 캡이 없으면 fullyParallel이 머신 코어 수만큼 worker를 띄워
  // 라이브 백엔드에 과한 동시성을 건다(flaky·부하). 기본 4, `E2E_LIVE_WORKERS`로 조정.
  workers: liveWorkers(),
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: redactedEvidence
    ? [["./e2e/c7-redacted-reporter.ts", { outputFolder: artifactRoot }]]
    : [
        ["list"],
        [
          "html",
          {
            open: "never",
            outputFolder: path.join(artifactRoot, "report"),
          },
        ],
      ],
  use: {
    baseURL,
    // 방어선(T-ADM-C7RUN): 기본 action/navigation timeout은 0(무제한)이라, 조건부 렌더
    // element를 기다리는 click/fill/goto가 조건이 끝내 참이 되지 않으면 spec의 30분
    // test-timeout까지 조용히 매달린다(관측된 empty-write hang의 근본 조건). 정상 UI
    // actionability·페이지 로드는 이보다 훨씬 빠르므로 통과 spec에 영향 없이, 무한 hang을
    // 상한 있는 명확한 실패로 바꾼다. spec별 장시간 대기는 explicit timeout(waitForTerminal 등)이 별도로 관리한다.
    actionTimeout: 60_000,
    navigationTimeout: 60_000,
    // C7 evidence에는 session cookie가 포함될 수 있는 trace ZIP을 남기지 않는다.
    trace: redactedEvidence ? "off" : "on-first-retry",
    // C7 evidence는 UI 운영 데이터가 픽셀에 남을 수 있는 screenshot도 생성하지 않는다.
    screenshot: redactedEvidence ? "off" : "only-on-failure",
  },
  projects: [
    // #520 인증 게이트 대응: chromium 전에 로그인 세션을 1회 만들어 STORAGE_STATE에 저장.
    // 세션은 user-agent fingerprint에 묶이므로, 셋업도 chromium과 동일 디바이스(=동일 UA)로
    // 로그인해야 chromium 테스트에서 세션이 유효하다.
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        extraHTTPHeaders: authRequestHeaders,
      },
    },
    {
      name: "chromium",
      testIgnore: /auth\.setup\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: LIVE_STORAGE_STATE },
      dependencies: ["setup"],
    },
  ],
});
