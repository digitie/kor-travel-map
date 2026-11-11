// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)

/** Docker의 지연 삭제가 끝날 때까지 성공한 빈 조회만 수용한다. */
export async function pollForResourceAbsence(
  listResources,
  {
    timeoutMs = 300_000,
    intervalMs = 500,
    now = () => performance.now(),
    sleep = (delay) => new Promise((resolve) => setTimeout(resolve, delay)),
  } = {},
) {
  const deadline = now() + timeoutMs;
  while (now() < deadline) {
    const remainingMs = deadline - now();
    const result = await listResources(remainingMs);
    if (now() <= deadline && result.status === 0 && result.stdout.trim() === "") return true;
    const delay = Math.min(intervalMs, deadline - now());
    if (delay > 0) await sleep(delay);
  }
  return false;
}
