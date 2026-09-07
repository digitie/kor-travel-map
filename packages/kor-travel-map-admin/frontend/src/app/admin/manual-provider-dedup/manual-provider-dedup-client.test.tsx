// @vitest-environment jsdom

/**
 * 인수조건 M05-5의 축들을 각각 결박한다 — 기본값 `kept`, provider survivor,
 * 파괴적 확인과 비어 있지 않은 사유, principal별 unacked age.
 *
 * 각 테스트는 **그 축을 지우면 빨개지도록** 쓴다 — 화면이 그리는지가 아니라
 * 화면이 **무엇을 막는지**를 본다.
 *
 * 앞선 판은 결함을 **정답으로 결박했다**: `manual_retired`에 survivor를 싣는 것을
 * 단언했는데 계약은 survivor를 `merged` 전용으로 막는다(라우터 model_validator와
 * DB `ck_m05_decision_input`). fetch mock이 payload와 무관하게 200을 줘서 그 위반이
 * 보이지 않았다. 여기서는 **mock이 계약을 흉내 낸다.**
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
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ManualProviderDedupClient } from "./manual-provider-dedup-client";

const META = {
  dataset_projection_revision: 1,
  duration_ms: 1,
  request_id: "test",
};

const CASE_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_CASE_ID = "55555555-5555-4555-8555-555555555555";
const FINGERPRINT = "a".repeat(64);

function summary(caseId: string, suffix: string) {
  return {
    case_id: caseId,
    status: "pending",
    created_at: "2026-09-08T00:00:00Z",
    evidence_fingerprint: FINGERPRINT,
    manual_feature: {
      feature_id: `f_manual_${suffix}`,
      feature_uuid: "22222222-2222-4222-8222-222222222222",
      row_revision: 3,
      snapshot: {},
    },
    provider_feature: {
      feature_id: `f_provider_${suffix}`,
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
}

const SUMMARY = summary(CASE_ID, "1");
const OTHER_SUMMARY = summary(OTHER_CASE_ID, "2");

/**
 * 구독은 **정렬되지 않은 순서**로 준다. 이미 정렬된 픽스처를 주면 `.sort()`를
 * 지워도 초록이라 정렬 축이 아무것도 지키지 않는다(적대 리뷰가 잡았다).
 */
const SUBSCRIPTIONS = [
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
    principal_id: "service:concierge",
    initial_event_sequence: 0,
    acked_through_sequence: 0,
    lease_epoch: 0,
    lease_expires_at: null,
    // 가장 오래 밀렸다 — 정렬 뒤 맨 위여야 한다.
    oldest_unacked_at: "2026-09-05T00:00:00Z",
    ack: null,
  },
  {
    principal_id: "service:acked",
    initial_event_sequence: 0,
    acked_through_sequence: 5,
    lease_epoch: 0,
    lease_expires_at: null,
    oldest_unacked_at: null,
    ack: null,
  },
];

function detail(base: ReturnType<typeof summary>) {
  return {
    ...base,
    manual_feature: {
      feature_id: base.manual_feature.feature_id,
      row_revision: base.manual_feature.row_revision,
    },
    provider_feature: {
      feature_id: base.provider_feature.feature_id,
      row_revision: base.provider_feature.row_revision,
    },
    scores: base.scores,
    resolution: null,
    event: null,
    subscriptions: SUBSCRIPTIONS,
  };
}

type Recorded = { url: string; init?: RequestInit; status: number };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function listBody(items: unknown[]) {
  return {
    data: {
      items,
      next_after_created_at: null,
      next_after_case_id: null,
    },
    meta: META,
  };
}

/**
 * 계약을 흉내 내는 mock.
 *
 * 서버는 `decision != 'merged'`인데 `survivor_feature_id`가 있으면 **422**다.
 * mock이 무조건 200을 주면 그 위반이 테스트에서 보이지 않는다 — 앞선 판이 정확히
 * 그렇게 결함을 통과시켰다.
 */
function context(decisionStatus = 0) {
  const calls: Recorded[] = [];
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/decisions")) {
        if (decisionStatus !== 0) {
          calls.push({ url, init, status: decisionStatus });
          return jsonResponse({ detail: "forced" }, decisionStatus);
        }
        const payload = JSON.parse(String(init?.body ?? "{}"));
        if (payload.decision !== "merged" && payload.survivor_feature_id != null) {
          calls.push({ url, init, status: 422 });
          return jsonResponse(
            {
              detail:
                "merged 이외 decision에는 survivor_feature_id를 둘 수 없습니다.",
            },
            422,
          );
        }
        calls.push({ url, init, status: 200 });
        return jsonResponse({
          data: {
            outcome: payload.decision,
            resolution_id: "44444444-4444-4444-8444-444444444444",
            event_id: "66666666-6666-4666-8666-666666666666",
            manual_feature_id: "f_manual_1",
            manual_feature_row_revision: 4,
          },
          meta: META,
        });
      }
      calls.push({ url, init, status: 200 });
      if (url.includes(OTHER_CASE_ID)) {
        return jsonResponse({ data: detail(OTHER_SUMMARY), meta: META });
      }
      if (url.includes(CASE_ID)) {
        return jsonResponse({ data: detail(SUMMARY), meta: META });
      }
      return jsonResponse(listBody([SUMMARY, OTHER_SUMMARY]));
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
function submitDisabled(): boolean {
  return (
    screen.getByRole("button", { name: "판정 제출" }) as HTMLButtonElement
  ).disabled;
}

function decisionPayload(calls: Recorded[]): Record<string, unknown> {
  const call = calls.find((entry) => entry.url.includes("/decisions"));
  return JSON.parse(String(call?.init?.body)) as Record<string, unknown>;
}

async function openCase(decisionStatus = 0) {
  const { calls, wrapper } = context(decisionStatus);
  render(<ManualProviderDedupClient />, { wrapper });
  fireEvent.click(await screen.findByRole("button", { name: /f_manual_1/ }));
  await screen.findByRole("heading", { name: "판정" });
  return calls;
}

function fillReason(reason: string) {
  fireEvent.change(screen.getByRole("textbox", { name: /사유/ }), {
    target: { value: reason },
  });
}

function chooseDestructive(label: RegExp) {
  fireEvent.click(screen.getByRole("radio", { name: label }));
  fireEvent.change(screen.getByRole("textbox", { name: /폐기를 확인합니다/ }), {
    target: { value: "폐기를 확인합니다" },
  });
}

beforeEach(() => {
  // 멱등 slot이 sessionStorage에 얼어붙어 다음 테스트로 새면, 그 테스트의 제출이
  // fingerprint mismatch로 죽거나 앞 테스트의 key를 재사용한다.
  window.sessionStorage.clear();
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("M05-5 admin 판정 화면", () => {
  it("기본 결정이 kept다 — 파괴적 판정이 기본이면 실수 한 번이 되돌릴 수 없다", async () => {
    await openCase();
    expect(
      (screen.getByRole("radio", { name: /유지/ }) as HTMLInputElement).checked,
    ).toBe(true);
    for (const name of [/병합/, /수동본 폐기/]) {
      expect(
        (screen.getByRole("radio", { name }) as HTMLInputElement).checked,
      ).toBe(false);
    }
  });

  it("사유가 비어 있으면 제출을 막는다", async () => {
    await openCase();
    expect(submitDisabled()).toBe(true);
    fillReason("중복 아님");
    expect(submitDisabled()).toBe(false);
  });

  it("파괴적 판정은 확인 문구를 그대로 받아야 열린다", async () => {
    await openCase();
    fillReason("provider가 정본");
    fireEvent.click(screen.getByRole("radio", { name: /수동본 폐기/ }));
    expect(submitDisabled()).toBe(true);

    const confirmation = screen.getByRole("textbox", { name: /폐기를 확인합니다/ });
    fireEvent.change(confirmation, { target: { value: "폐기" } });
    expect(submitDisabled()).toBe(true);

    fireEvent.change(confirmation, { target: { value: "폐기를 확인합니다" } });
    expect(submitDisabled()).toBe(false);
  });

  it("merged에는 provider survivor를 싣는다", async () => {
    const calls = await openCase();
    fillReason("provider가 정본");
    chooseDestructive(/병합/);
    fireEvent.click(screen.getByRole("button", { name: "판정 제출" }));
    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/decisions"))).toBe(true);
    });
    const payload = decisionPayload(calls);
    expect(payload.decision).toBe("merged");
    expect(payload.survivor_feature_id).toBe("f_provider_1");
    // 낙관적 동시성 세 값이 실제 case에서 온다.
    expect(payload.expected_case_fingerprint).toBe(FINGERPRINT);
    expect(payload.expected_manual_row_revision).toBe(3);
    expect(payload.expected_provider_row_revision).toBe(7);
  });

  it("manual_retired는 survivor 없이 보내고 서버가 받아들인다", async () => {
    const calls = await openCase();
    fillReason("수동본이 잘못됐다");
    chooseDestructive(/수동본 폐기/);
    fireEvent.click(screen.getByRole("button", { name: "판정 제출" }));
    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/decisions"))).toBe(true);
    });
    const payload = decisionPayload(calls);
    expect(payload.decision).toBe("manual_retired");
    // **여기가 앞선 판이 뒤집혀 있던 자리다.** 계약은 survivor를 merged 전용으로 막는다.
    expect(payload.survivor_feature_id).toBeNull();
    expect(
      calls.find((call) => call.url.includes("/decisions"))?.status,
    ).toBe(200);
    // 판정 결과를 화면이 버리지 않는다.
    await screen.findByRole("region", { name: "판정 결과" });
  });

  it("멱등 키를 헤더에 싣고 slot 이름이 admin. 접두를 지킨다", async () => {
    const calls = await openCase();
    fillReason("중복 아님");
    fireEvent.click(screen.getByRole("button", { name: "판정 제출" }));
    await waitFor(() => {
      expect(calls.some((call) => call.url.includes("/decisions"))).toBe(true);
    });
    const decision = calls.find((call) => call.url.includes("/decisions"));
    const headers = new Headers(decision?.init?.headers);
    expect(headers.get("Idempotency-Key")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
    // `Storage`는 `Object.keys`로 열거되지 않는다 — `key(i)`로 읽어야 한다.
    const slots: string[] = [];
    for (let index = 0; index < window.sessionStorage.length; index += 1) {
      const key = window.sessionStorage.key(index);
      if (key && key.includes("manual-provider-dedup")) {
        slots.push(key);
      }
    }
    expect(slots.length).toBeGreaterThan(0);
    for (const slot of slots) {
      expect(slot).toContain("admin.");
    }
  });

  it("principal별 unacked age를 오래된 순으로 보이고, 밀리지 않은 principal은 빼놓는다", async () => {
    await openCase();
    const region = screen.getByRole("region", { name: "미확인 consumer" });
    const items = within(region).getAllByRole("listitem");
    expect(items[0].textContent).toContain("service:concierge");
    expect(items[1].textContent).toContain("service:pinvi");
    expect(region.textContent).not.toContain("service:acked");
  });

  it("case를 바꾸면 판정 입력이 초기화된다 — 앞 case의 확인 문구로 다음 case가 무장되면 안 된다", async () => {
    await openCase();
    fillReason("provider가 정본");
    chooseDestructive(/수동본 폐기/);
    expect(submitDisabled()).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /f_manual_2/ }));
    // 패널이 remount되므로 상세를 다시 불러온다 — 라디오가 그 뒤에 나타난다.
    await waitFor(() => {
      expect(screen.queryByRole("radio", { name: /유지/ })).not.toBeNull();
    });
    expect(
      (screen.getByRole("radio", { name: /유지/ }) as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByRole("textbox", { name: /사유/ }) as HTMLTextAreaElement).value,
    ).toBe("");
    expect(submitDisabled()).toBe(true);
  });

  it("409를 stale로 구별해 설명한다 — 전부 한 문장으로 뭉개면 무엇을 해야 할지 알 수 없다", async () => {
    await openCase(409);
    fillReason("중복 아님");
    fireEvent.click(screen.getByRole("button", { name: "판정 제출" }));
    const alert = await screen.findByText(/후보가 그 사이 바뀌었다/);
    expect(alert.textContent).toContain("다시 열어");
  });

  it("422는 계약 위반으로 구별해 설명한다", async () => {
    await openCase(422);
    fillReason("중복 아님");
    fireEvent.click(screen.getByRole("button", { name: "판정 제출" }));
    await screen.findByText(/요청이 계약을 어겼다/);
  });
});
