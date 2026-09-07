// @vitest-environment jsdom

/**
 * 인수조건 M05-5의 네 축을 각각 결박한다 — 기본값 `kept`, provider survivor 고정,
 * 파괴적 확인과 비어 있지 않은 사유, principal별 unacked age. 그리고 generic dedup
 * 화면을 재사용하지 않는다는 축도 함께 잰다.
 *
 * 각 테스트는 **그 축을 지우면 빨개지도록** 쓴다 — 화면이 그리는지가 아니라
 * 화면이 **무엇을 막는지**를 본다.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ManualProviderDedupClient } from "./manual-provider-dedup-client";

const META = {
  dataset_projection_revision: 1,
  duration_ms: 1,
  request_id: "test",
};

const CASE_ID = "11111111-1111-4111-8111-111111111111";
const FINGERPRINT = "a".repeat(64);

const SUMMARY = {
  case_id: CASE_ID,
  status: "pending",
  created_at: "2026-09-08T00:00:00Z",
  evidence_fingerprint: FINGERPRINT,
  manual_feature: {
    feature_id: "f_manual_1",
    feature_uuid: "22222222-2222-4222-8222-222222222222",
    row_revision: 3,
    snapshot: {},
  },
  provider_feature: {
    feature_id: "f_provider_1",
    feature_uuid: "33333333-3333-4333-8333-333333333333",
    row_revision: 7,
    snapshot: {},
  },
  scores: {
    scorer_id: "manual-provider-v1",
    scorer_input_sha256: "b".repeat(64),
    name_score: 0.9,
    spatial_score: 0.95,
    category_score: 1,
    total_score: 0.93,
    distance_meters: 12.3,
  },
};

const DETAIL = {
  ...SUMMARY,
  manual_feature: { feature_id: "f_manual_1", row_revision: 3 },
  provider_feature: { feature_id: "f_provider_1", row_revision: 7 },
  scores: SUMMARY.scores,
  resolution: null,
  event: null,
  subscriptions: [
    {
      principal_id: "service:concierge",
      initial_event_sequence: 0,
      acked_through_sequence: 0,
      lease_epoch: 0,
      lease_expires_at: null,
      // 오래 밀린 쪽 — 위에 와야 한다.
      oldest_unacked_at: "2026-09-05T00:00:00Z",
      ack: null,
    },
    {
      principal_id: "service:pinvi",
      initial_event_sequence: 0,
      acked_through_sequence: 0,
      lease_epoch: 0,
      lease_expires_at: null,
      oldest_unacked_at: "2026-09-07T22:00:00Z",
      ack: null,
    },
    {
      principal_id: "service:acked",
      initial_event_sequence: 0,
      acked_through_sequence: 5,
      lease_epoch: 0,
      lease_expires_at: null,
      // 밀린 것이 없다 — 목록에 나오면 안 된다.
      oldest_unacked_at: null,
      ack: null,
    },
  ],
};

type Recorded = { url: string; init?: RequestInit };

function context() {
  const calls: Recorded[] = [];
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      const json = (body: unknown) =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      if (url.includes("/decisions")) {
        return json({
          data: {
            outcome: "manual_retired",
            resolution_id: "44444444-4444-4444-8444-444444444444",
            event_id: null,
            manual_feature_id: "f_manual_1",
            manual_feature_row_revision: 4,
          },
          meta: META,
        });
      }
      if (url.includes(CASE_ID)) {
        return json({ data: DETAIL, meta: META });
      }
      return json({
        data: {
          items: [SUMMARY],
          next_after_created_at: null,
          next_after_case_id: null,
        },
        meta: META,
      });
    },
  );
  vi.stubGlobal("fetch", fetchMock);

  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { calls, wrapper };
}

/** `@testing-library/jest-dom`을 쓰지 않으므로 속성을 직접 읽는다. */
function submitButton(): boolean {
  return (
    screen.getByRole("button", { name: "판정 제출" }) as HTMLButtonElement
  ).disabled;
}

async function openCase() {
  const { calls, wrapper } = context();
  render(<ManualProviderDedupClient />, { wrapper });
  const summary = await screen.findByRole("button", { name: /f_manual_1/ });
  fireEvent.click(summary);
  await screen.findByRole("heading", { name: "판정" });
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("M05-5 admin 판정 화면", () => {
  it("기본 결정이 kept다 — 파괴적 판정이 기본이면 실수 한 번이 되돌릴 수 없다", async () => {
    await openCase();
    const kept = screen.getByRole("radio", { name: /유지/ });
    expect((kept as HTMLInputElement).checked).toBe(true);
    for (const name of [/병합/, /수동본 폐기/]) {
      expect((screen.getByRole("radio", { name }) as HTMLInputElement).checked).toBe(
        false,
      );
    }
  });

  it("사유가 비어 있으면 제출을 막는다", async () => {
    await openCase();
    expect(submitButton()).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: /사유/ }), { target: { value: "중복 아님" } });
    expect(submitButton()).toBe(false);
  });

  it("파괴적 판정은 확인 문구를 그대로 받아야 열린다", async () => {
    await openCase();
    fireEvent.change(screen.getByRole("textbox", { name: /사유/ }), { target: { value: "provider가 정본" } });
    fireEvent.click(screen.getByRole("radio", { name: /수동본 폐기/ }));

    expect(submitButton()).toBe(true);

    const confirmation = screen.getByRole("textbox", { name: /폐기를 확인합니다/ });
    fireEvent.change(confirmation, { target: { value: "폐기" } });
    expect(submitButton()).toBe(true);

    fireEvent.change(confirmation, { target: { value: "폐기를 확인합니다" } });
    expect(submitButton()).toBe(false);
  });

  it("survivor는 provider로 고정이다 — 고를 수 없고 제출 payload에도 provider가 실린다", async () => {
    const calls = await openCase();
    fireEvent.change(screen.getByRole("textbox", { name: /사유/ }), { target: { value: "provider가 정본" } });
    fireEvent.click(screen.getByRole("radio", { name: /수동본 폐기/ }));
    fireEvent.change(screen.getByRole("textbox", { name: /폐기를 확인합니다/ }), { target: { value: "폐기를 확인합니다" } });
    fireEvent.click(screen.getByRole("button", { name: "판정 제출" }));

    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/decisions"))).toBe(true);
    });
    const decision = calls.find((call) => call.url.includes("/decisions"));
    const payload = JSON.parse(String(decision?.init?.body));
    expect(payload.survivor_feature_id).toBe("f_provider_1");
    expect(payload.decision).toBe("manual_retired");
    // 낙관적 동시성 세 값이 실제 case에서 온다 — 지어내면 서버가 409로 막지만
    // 화면이 조용히 틀린 값을 보내면 그 409의 원인이 보이지 않는다.
    expect(payload.expected_case_fingerprint).toBe(FINGERPRINT);
    expect(payload.expected_manual_row_revision).toBe(3);
    expect(payload.expected_provider_row_revision).toBe(7);
    // survivor를 고르는 컨트롤이 있으면 안 된다.
    expect(screen.queryByRole("radio", { name: /survivor/i })).toBeNull();
  });

  it("멱등 키를 헤더에 싣는다", async () => {
    const calls = await openCase();
    fireEvent.change(screen.getByRole("textbox", { name: /사유/ }), { target: { value: "중복 아님" } });
    fireEvent.click(screen.getByRole("button", { name: "판정 제출" }));
    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/decisions"))).toBe(true);
    });
    const decision = calls.find((call) => call.url.includes("/decisions"));
    const headers = new Headers(decision?.init?.headers);
    expect(headers.get("Idempotency-Key")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
  });

  it("principal별 unacked age를 오래된 순으로 보이고, 밀리지 않은 principal은 빼놓는다", async () => {
    await openCase();
    const list = screen.getByRole("region", { name: "미확인 consumer" });
    const items = within(list).getAllByRole("listitem");
    expect(items[0].textContent).toContain("service:concierge");
    expect(items[1].textContent).toContain("service:pinvi");
    expect(list.textContent).not.toContain("service:acked");
  });
});
