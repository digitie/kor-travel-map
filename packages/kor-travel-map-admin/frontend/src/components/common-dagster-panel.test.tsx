// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";

import { getJson } from "@/api/client";
import { CommonDagsterPanel } from "./common-dagster-panel";

vi.mock("@/api/client", () => ({ getJson: vi.fn() }));
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
