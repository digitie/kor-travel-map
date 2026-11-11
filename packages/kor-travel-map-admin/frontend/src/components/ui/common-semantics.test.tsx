// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { CardTitle } from "./card";
import { Alert } from "./alert";

afterEach(cleanup);

it("공통 CardTitle도 기존 Map heading 수준과 명시 수준을 유지한다", () => {
  render(
    <>
      <CardTitle>선택 없음</CardTitle>
      <CardTitle aria-level={3}>상세</CardTitle>
    </>,
  );
  expect(
    screen.getByRole("heading", { name: "선택 없음", level: 2 }),
  ).toBeTruthy();
  expect(screen.getByRole("heading", { name: "상세", level: 3 })).toBeTruthy();
});

it("일반 작업 결과는 status, 오류는 alert이며 호출부 역할을 우선한다", () => {
  render(
    <>
      <Alert>backup command planned</Alert>
      <Alert variant="destructive">오류</Alert>
      <Alert variant="destructive" role="status" aria-live="off">
        직접 제어
      </Alert>
    </>,
  );
  expect(screen.getAllByRole("status")[0]?.textContent).toContain(
    "backup command planned",
  );
  expect(screen.getByRole("alert").getAttribute("aria-live")).toBe("assertive");
  expect(screen.getByText("직접 제어").getAttribute("aria-live")).toBe("off");
});
