// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { McstAttemptError } from "./mcst-attempt-error";

afterEach(cleanup);
const error = {
  code: "MCST_DATASET_FETCH_FAILED",
  phase: "fetch",
  reason: "CAPTCHA_REQUIRED",
  retryable: false,
};

it("안전한 진단과 실제 작업 이동을 제공하고 부가 원문은 표시하지 않는다", () => {
  const select = vi.fn();
  render(<McstAttemptError error={{ ...error, body: "SECRET_BODY" }} onSelectJob={select} />);
  expect(screen.getByLabelText("데이터셋 실패 원인").textContent).toContain("수집");
  expect(screen.getByText("CAPTCHA_REQUIRED")).toBeTruthy();
  expect(screen.getByText(/재시도: 불가/)).toBeTruthy();
  expect(screen.queryByText("SECRET_BODY")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "실패한 데이터셋 작업 보기" }));
  expect(select).toHaveBeenCalledOnce();
});

it.each([
  null, [], { ...error, reason: "HTTP URL ?token=SECRET" },
  { ...error, code: "UNKNOWN" }, { ...error, retryable: "false" },
  { ...error, phase: "toString" },
])("검증되지 않은 payload는 노출하지 않는다: %j", (value) => {
  const { container } = render(<McstAttemptError error={value} />);
  expect(container.textContent).toBe("");
});
