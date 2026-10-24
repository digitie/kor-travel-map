// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { HelpTip } from "./help-tip";

afterEach(cleanup);

it("정보 아이콘은 제목 옆 버튼으로 안내를 열고 닫는다", async () => {
  render(<HelpTip label="Feature 지도" variant="info">추가 필터에서 상태를 선택합니다.</HelpTip>);
  const button = screen.getByRole("button", { name: "도움말: Feature 지도" });
  expect(button.querySelector("svg.lucide-info")).not.toBeNull();
  expect(screen.queryByText("추가 필터에서 상태를 선택합니다.")).toBeNull();
  fireEvent.click(button);
  expect(await screen.findByText("추가 필터에서 상태를 선택합니다.")).toBeTruthy();
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  await waitFor(() => expect(screen.queryByText("추가 필터에서 상태를 선택합니다.")).toBeNull());
});

it("다른 화면의 기존 도움말 아이콘은 유지한다", () => {
  render(<HelpTip label="기존 항목">도움말</HelpTip>);
  expect(screen.getByRole("button", { name: "도움말: 기존 항목" }).querySelector("svg.lucide-circle-question-mark")).not.toBeNull();
});
