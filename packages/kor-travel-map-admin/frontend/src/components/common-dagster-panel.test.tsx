// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";

import { usePipelineDagsterRunDetail } from "@/api/pipeline";

import { getJson } from "@/api/client";
import { CommonDagsterPanel } from "./common-dagster-panel";

vi.mock("@/api/client", () => ({ getJson: vi.fn() }));
vi.mock("@/api/pipeline", async () => ({
  ...await vi.importActual("@/api/pipeline"), usePipelineDagsterRunDetail: vi.fn(),
}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("HTTP 200 degraded 조회가 마지막 정상 실행을 지우지 않는다", async () => {
  const checkedAt = "2026-10-05T00:00:00Z";
  vi.mocked(getJson).mockResolvedValueOnce({ data: {
    status: "ok", checked_at: checkedAt, dagster_url: "http://dagster.test",
    repositories: [], recent_runs: [{ run_id: "old-active", job_name: "map_hanging_job", status: "STARTED",
      start_time: 1, end_time: null, tags: { "dagster/max_runtime": "120" } }],
  }}).mockResolvedValue({ data: { status: "unavailable", recent_runs: [], repositories: [] }});
  const cache = new QueryClient();
  render(<QueryClientProvider client={cache}><CommonDagsterPanel /></QueryClientProvider>);
  await screen.findByText("map_hanging_job");
  fireEvent.click(screen.getByRole("button", { name: "새로고침" }));
  await waitFor(() => expect(screen.getByText(/Dagster 연결을 확인하지 못했습니다/)).toBeTruthy(), { timeout: 5000 });
  expect(screen.getByText("map_hanging_job")).toBeTruthy();
  expect(screen.getAllByText(/정체 의심/).length).toBeGreaterThan(0);
  cache.clear();
});


it("선택한 실패 run의 원인과 다음 이벤트 페이지를 기존 조회로 표시한다", async () => {
  vi.mocked(getJson).mockResolvedValue({ data: {
    status: "ok", checked_at: "2026-10-05T00:00:00Z", dagster_url: "http://dagster.test",
    repositories: [], recent_runs: [{ run_id: "failed-run", job_name: "map_failed_job", status: "FAILURE",
      start_time: 1, end_time: 2, tags: {} }],
  }});
  vi.mocked(usePipelineDagsterRunDetail).mockImplementation((_runId, options) => ({
    data: { data: { failure_reason: "fixture failure", events: [{ message: options?.after ? "second event" : "first event" }],
      event_cursor: options?.after ? null : "next", event_has_more: !options?.after } },
    isLoading: false, isError: false, isFetching: false,
  } as unknown as ReturnType<typeof usePipelineDagsterRunDetail>));
  const cache = new QueryClient();
  render(<QueryClientProvider client={cache}><CommonDagsterPanel /></QueryClientProvider>);
  const select = await screen.findByRole("button", { name: "실행 상세: map_failed_job, failed-run" });
  expect(vi.mocked(usePipelineDagsterRunDetail)).not.toHaveBeenCalled();
  fireEvent.click(select);
  await screen.findByText("fixture failure");
  expect(screen.getByText("first event")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "다음 이벤트 페이지" }));
  await screen.findByText("second event");
  expect(vi.mocked(usePipelineDagsterRunDetail)).toHaveBeenLastCalledWith("failed-run", { page_size: 50, after: "next" });
  fireEvent.click(select);
  expect(screen.queryByText("fixture failure")).toBeNull();
  cache.clear();
});
