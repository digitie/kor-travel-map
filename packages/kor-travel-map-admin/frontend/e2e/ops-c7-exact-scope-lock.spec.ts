import { mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { acquireC7ExactScopeLock } from "./live/_ops-c7-exact-scope-lock";

/**
 * 잠금 자체를 검증한다. live spec 안에서만 쓰이면 이 계약은 실제 live 실행 때
 * **처음** 확인되고, 그때 틀리면 75분짜리 write spec 네 개가 함께 오염된다.
 */

function lockDirectory(scope: string): string {
  const safe = scope.replace(/[^a-z0-9_-]+/gi, "_");
  return join(tmpdir(), `kor-travel-map-c7-exact-scope-${safe}.lock`);
}

async function clearLock(scope: string): Promise<void> {
  await rm(lockDirectory(scope), { force: true, recursive: true });
}

test("두 취득자는 겹치지 않는다 — 먼저 잡은 쪽이 놓아야 다음이 들어온다", async () => {
  const scope = `external_system:lock-mutual-${process.pid}`;
  await clearLock(scope);
  const order: string[] = [];
  const release = await acquireC7ExactScopeLock(scope, 30_000);
  order.push("first-acquired");

  const second = acquireC7ExactScopeLock(scope, 30_000).then((releaseSecond) => {
    order.push("second-acquired");
    return releaseSecond;
  });
  // 잠금이 실제로 막고 있다면 이 시점에 second는 아직 들어오지 못한다. 이 단언이
  // 없으면 "그냥 둘 다 성공"과 구별되지 않는다.
  await new Promise((resolve) => setTimeout(resolve, 1200));
  expect(order).toEqual(["first-acquired"]);

  order.push("first-released");
  await release();
  const releaseSecond = await second;
  expect(order).toEqual([
    "first-acquired",
    "first-released",
    "second-acquired",
  ]);
  await releaseSecond();
  await clearLock(scope);
});

test("해제는 멱등이다 — 두 번 불러도 다음 취득자를 깨뜨리지 않는다", async () => {
  const scope = `external_system:lock-idempotent-${process.pid}`;
  await clearLock(scope);
  const release = await acquireC7ExactScopeLock(scope, 10_000);
  await release();
  await release();

  const again = await acquireC7ExactScopeLock(scope, 10_000);
  await again();
  await clearLock(scope);
});

test("죽은 소유자의 잠금은 회수한다 — crash 한 번이 이후 실행을 영구 차단하지 않는다", async () => {
  const scope = `external_system:lock-stale-${process.pid}`;
  const directory = lockDirectory(scope);
  await clearLock(scope);
  await mkdir(directory, { recursive: true });
  // 존재하지 않는 pid를 소유자로 심는다. 아주 큰 pid는 살아 있을 수 없다.
  await writeFile(
    join(directory, "owner.json"),
    JSON.stringify({ acquiredAt: Date.now(), pid: 2 ** 30, scope }),
    { encoding: "utf8" },
  );

  const release = await acquireC7ExactScopeLock(scope, 10_000);

  await release();
  await clearLock(scope);
});

test("소유자를 읽을 수 없는 잠금은 회수하지 않는다 — 취득 직후 경합을 빼앗지 않는다", async () => {
  const scope = `external_system:lock-unreadable-${process.pid}`;
  const directory = lockDirectory(scope);
  await clearLock(scope);
  // mkdir은 됐지만 owner.json을 아직 못 쓴 상태 = 정상 취득자의 찰나.
  await mkdir(directory, { recursive: true });

  await expect(acquireC7ExactScopeLock(scope, 1_500)).rejects.toThrow(
    /잠금 대기 시간 초과/,
  );

  await clearLock(scope);
});
