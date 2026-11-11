// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)
import { describe, expect, it } from "vitest";
import { pollForResourceAbsence } from "../e2e/mocked-checkpoint-cleanup.mjs";

function clock() {
  let elapsed = 0;
  return { now: () => elapsed, sleep: async (delay) => { elapsed += delay; } };
}

describe("소유 Docker 자원의 엄격한 삭제 후조건", () => {
  it("기존 2초 확인 구간보다 늦게 삭제돼도 실제 빈 조회 뒤에만 성공한다", async () => {
    const time = clock();
    const observations = [];
    const result = await pollForResourceAbsence(async () => {
      observations.push(time.now());
      return { status: 0, stdout: time.now() < 45_000 ? "owned-container-id\n" : "" };
    }, time);
    expect(result).toBe(true);
    expect(observations.at(-1)).toBe(45_000);
    expect(observations.length).toBeGreaterThan(20);
  });

  it("자원이 계속 남으면 제한 시간이 끝나도 성공으로 바꾸지 않는다", async () => {
    const time = clock();
    const budgets = [];
    expect(await pollForResourceAbsence(async (remaining) => {
      budgets.push(remaining);
      return { status: 0, stdout: "owned-container-id" };
    }, { ...time, timeoutMs: 1_200 })).toBe(false);
    expect(time.now()).toBe(1_200);
    expect(budgets).toEqual([1_200, 700, 200]);
  });

  it("실패한 조회의 빈 stdout은 부재 증거가 아니다", async () => {
    const time = clock();
    expect(await pollForResourceAbsence(async () => ({ status: 1, stdout: "" }),
      { ...time, timeoutMs: 1_000 })).toBe(false);
  });

  it("조회 실패 뒤 성공한 빈 조회를 확인하면 종료한다", async () => {
    const time = clock();
    let attempts = 0;
    expect(await pollForResourceAbsence(async () => ({
      status: ++attempts === 1 ? 1 : 0, stdout: "",
    }), time)).toBe(true);
    expect(attempts).toBe(2);
  });
  it("남은 예산을 넘긴 조회 결과는 성공한 빈 응답이어도 제한을 우회하지 않는다", async () => {
    const time = clock();
    expect(await pollForResourceAbsence(async (remaining) => {
      await time.sleep(remaining + 1);
      return { status: 0, stdout: "" };
    }, { ...time, timeoutMs: 1_000 })).toBe(false);
  });
});
