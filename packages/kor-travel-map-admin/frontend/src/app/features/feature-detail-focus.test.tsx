// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { FeatureDetailPanel } from "./features-client";

vi.mock("@/components/vworld-map-view", () => ({}));
vi.mock("@/api/features", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/features")>(),
  useAdminFeatureDetail: () => ({ isLoading: true, isError: false, data: undefined }),
}));

const frames = new Map<number, FrameRequestCallback>();
let nextFrame = 0;
beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
    frames.set(++nextFrame, callback);
    return nextFrame;
  }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn((id: number) => frames.delete(id)));
});
afterEach(() => { cleanup(); frames.clear(); document.body.replaceChildren(); vi.unstubAllGlobals(); });

for (const method of ["Escape", "닫기"]) {
  it(`${method}: 상세 진입 후 열었던 버튼으로 포커스를 복원한다`, () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const onClose = vi.fn();
    render(<FeatureDetailPanel featureId="qa" onClose={onClose} />);
    const panel = screen.getByTestId("feature-detail-panel");
    act(() => { for (const [id, callback] of frames) { frames.delete(id); callback(0); } });
    expect(document.activeElement).toBe(panel);
    if (method === "Escape") fireEvent.keyDown(panel, { key: "Escape" });
    else fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(opener);
  });
}

it("진입 프레임 전에 사라진 패널은 예약된 포커스를 취소한다", () => {
  const { unmount } = render(<FeatureDetailPanel featureId="qa" onClose={vi.fn()} />);
  const id = nextFrame;
  expect(frames.has(id)).toBe(true);
  unmount();
  expect(cancelAnimationFrame).toHaveBeenCalledWith(id);
  expect(frames.has(id)).toBe(false);
});
