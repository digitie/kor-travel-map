// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "./login-form";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LoginForm", () => {
  it("submit uses current form values instead of stale React state", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<LoginForm nextPath="/" />);

    const passwordInput = screen.getByLabelText("비밀번호") as HTMLInputElement;
    passwordInput.value = "typed-secret";

    const button = screen.getByRole("button", { name: "로그인" });
    const form = button.closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      username: "admin",
      password: "typed-secret",
      next: "/",
    });
  });
});

it("네트워크 실패는 오류를 표시하고 비밀번호를 지워 다시 제출할 수 있다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private network detail")));
  render(<LoginForm nextPath="/" />);
  const input = screen.getByLabelText("비밀번호") as HTMLInputElement;
  input.value = "synthetic-input";
  fireEvent.submit(screen.getByRole("button", { name: "로그인" }).closest("form") as HTMLFormElement);
  await screen.findByText("로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.");
  expect(input.value).toBe("");
  expect(screen.queryByText("private network detail")).toBeNull();
});
