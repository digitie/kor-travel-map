import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

/**
 * 고정 `external_system:*` scope를 쓰는 live spec들을 **worker 사이에서** 직렬화한다.
 *
 * 왜 필요한가. live config은 `fullyParallel: true`이고 worker 기본값이 4다. 반면
 * `external_system:c7-e2e`를 쓰는 KMA live spec들은 카탈로그가 선언한 scope 행 하나와
 * 그에 붙은 `provider_sync_state(dataset, external_system:c7-e2e, operation)` **한 행**을
 * 공유한다. 동시에 돌면 서로의 `membership_fingerprint`와 cursor를 덮어써서, 실패가
 * 실제 회귀인지 경합인지 구분할 수 없는 증거가 나온다.
 *
 * 왜 파일 병합이 아닌가. `test.describe.configure({ mode: "serial" })`는 **한 파일 안**
 * 에서만 순서를 강제한다. 네 spec을 한 파일로 합치면 1,500줄 넘는 기계적 병합에
 * 상수 이름 충돌까지 얹혀 회귀 위험이 크고, scope를 쓰는 spec이 하나 늘 때마다 다시
 * 합쳐야 한다. 잠금은 제약을 있는 그대로 표현하고 spec 수와 무관하게 성립한다.
 *
 * 왜 `mkdir`인가. POSIX `mkdir`은 원자적이라 별도 의존성 없이 상호배제가 된다.
 * 그 대신 잡은 쪽이 죽으면 디렉터리가 남으므로, 소유자 pid의 생존과 나이 상한을
 * 함께 본다 — 둘 다 없으면 한 번의 crash가 이후 모든 실행을 영구 차단한다.
 */

/** 이 상한을 넘긴 잠금은 소유자가 살아 있어도 stale로 본다. 최장 spec(75분)보다 길다. */
const STALE_LOCK_MS = 100 * 60 * 1000;
const ACQUIRE_POLL_MS = 500;

export type C7ExactScopeLockRelease = () => Promise<void>;

type LockOwner = { acquiredAt: number; pid: number; scope: string };

function lockDirectory(scope: string): string {
  // scope는 `external_system:c7-e2e` 형태라 경로 문자로 쓸 수 없다.
  const safe = scope.replace(/[^a-z0-9_-]+/gi, "_");
  return join(tmpdir(), `kor-travel-map-c7-exact-scope-${safe}.lock`);
}

function ownerIsAlive(owner: LockOwner): boolean {
  try {
    // signal 0은 프로세스를 건드리지 않고 존재만 확인한다.
    process.kill(owner.pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function readOwner(directory: string): Promise<LockOwner | null> {
  try {
    const raw = await readFile(join(directory, "owner.json"), "utf8");
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      typeof (parsed as LockOwner).pid !== "number" ||
      typeof (parsed as LockOwner).acquiredAt !== "number" ||
      typeof (parsed as LockOwner).scope !== "string"
    ) {
      return null;
    }
    return parsed as LockOwner;
  } catch {
    return null;
  }
}

/** 소유자가 죽었거나 나이 상한을 넘긴 잠금만 회수한다. */
async function reclaimIfStale(directory: string, now: number): Promise<boolean> {
  const owner = await readOwner(directory);
  // owner를 읽을 수 없는 잠금은 **회수하지 않는다**. 방금 mkdir하고 owner.json을
  // 쓰기 직전인 정상 취득자를 빼앗을 수 있기 때문이다. 나이 상한으로만 푼다.
  if (owner === null) return false;
  if (ownerIsAlive(owner) && now - owner.acquiredAt < STALE_LOCK_MS) return false;
  await rm(directory, { force: true, recursive: true });
  return true;
}

/**
 * scope 잠금을 잡고 해제 함수를 돌려준다. 이미 잡혀 있으면 풀릴 때까지 기다린다.
 *
 * @param scope 고정 exact-target scope (예: `external_system:c7-e2e`)
 * @param timeoutMs 대기 상한. 넘기면 throw한다 — 조용히 병렬 실행되는 것보다 낫다.
 */
export async function acquireC7ExactScopeLock(
  scope: string,
  timeoutMs = STALE_LOCK_MS,
): Promise<C7ExactScopeLockRelease> {
  const directory = lockDirectory(scope);
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      await mkdir(directory, { recursive: false });
      const owner: LockOwner = {
        acquiredAt: Date.now(),
        pid: process.pid,
        scope,
      };
      await writeFile(join(directory, "owner.json"), JSON.stringify(owner), {
        encoding: "utf8",
      });
      let released = false;
      return async () => {
        if (released) return;
        released = true;
        await rm(directory, { force: true, recursive: true });
      };
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== "EEXIST") throw error;
      const now = Date.now();
      if (await reclaimIfStale(directory, now)) continue;
      if (now >= deadline) {
        throw new Error(
          `C7 exact-scope 잠금 대기 시간 초과: ${scope} (동시 실행 중인 spec이 있습니다)`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, ACQUIRE_POLL_MS));
    }
  }
}
