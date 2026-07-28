import type { TestStep } from "@playwright/test/reporter";
import { describe, expect, it } from "vitest";

import { firstFailureStageMatches } from "../e2e/mocked-failure-reporter";

function step(category: string, title: string): TestStep {
  return { category, title } as TestStep;
}

describe("mocked failure stage provenance", () => {
  it("같은 auth locator라도 beforeEach hook 밖이면 auth로 분류하지 않는다", () => {
    const authHook = [
      step("hook", "Before Hooks"),
      step("hook", "beforeEach hook"),
      step("pw:api", "Fill \"admin\" locator('#admin-username')"),
    ];
    const testBody = [authHook.at(-1)!];

    expect(firstFailureStageMatches("beforeEach.auth", authHook)).toBe(true);
    expect(firstFailureStageMatches("interaction", authHook)).toBe(false);
    expect(firstFailureStageMatches("beforeEach.auth", testBody)).toBe(false);
    expect(firstFailureStageMatches("interaction", testBody)).toBe(true);
  });

  it("render와 request assertion step title을 배타적으로 분류한다", () => {
    const render = [
      step(
        "expect",
        "Expect \"toBeVisible\" getByRole('heading', { name: '운영 홈' })",
      ),
    ];
    const request = [step("expect", 'Expect "toMatchObject"')];

    expect(firstFailureStageMatches("render.assertion", render)).toBe(true);
    expect(firstFailureStageMatches("request.assertion", render)).toBe(false);
    expect(firstFailureStageMatches("render.assertion", request)).toBe(false);
    expect(firstFailureStageMatches("request.assertion", request)).toBe(true);
  });

  it("Playwright step이 없는 route mock 예외만 mock.install로 분류한다", () => {
    expect(firstFailureStageMatches("mock.install", [])).toBe(true);
    expect(
      firstFailureStageMatches("mock.install", [
        step("pw:api", "Navigate to /ops/datasets"),
      ]),
    ).toBe(false);
  });
});
