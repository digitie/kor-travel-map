/**
 * T-VN-H22C — 0065 quarantine 재분류 파괴적 live 검증.
 *
 * **prod에서 돌리지 마라.** 이 spec은 격리 clone 전용이다:
 * 실데이터 quarantine은 0건이고 구조상 영구 0건이므로(H22 착수 전 실측), 검증 대상은
 * 러너가 DB에 **합성**해야 한다. 합성 레시피는
 * (옛 `tests/integration/test_h35_cutover_rehearsal.py`의 `_plant_quarantine_candidate`와
 * 같은 형상이었다. 그 파일은 `df9237a3`에서 이미 삭제됐다.)
 * 격리 후보 planting은
 * 같은 계열 — legacy-marker collection에 canonical-only item을 심고 `0065`를 통과시키거나,
 * head 스키마에서 quarantine marker collection(`created_by='migration:0065'`,
 * `metadata.migration_quarantine='0065'`, `metadata.original_collection_id`)을 직접 만든다.
 *
 * 필요 env (하나라도 없으면 skip — 파괴적 스텝은 write flag 없으면 조회만 한다):
 *   E2E_QUARANTINE_COLLECTION_ID   합성된 격리 collection uuid
 *   E2E_QUARANTINE_WRITE=1         move/confirm 파괴 스텝 opt-in
 *   E2E_LIVE_WORKERS=1             write 스텝은 직렬 실행을 단언한다 — live config
 *                                  기본(workers=4)으로 돌리면 파괴 실행 대신 단언 실패
 *   E2E_QUARANTINE_EXPECT_CONFLICT_ITEM_ID  (선택) 충돌이 나도록 합성된 item uuid
 */
import { expect, test } from "@playwright/test";

type QuarantineCollection = {
  command_etag: string;
  collection_id: string;
  collection_key: string;
  item_count: number;
  marker_intact: boolean;
  original_collection: { collection_id: string; exists: boolean } | null;
  title: string;
};

type QuarantineItem = {
  conflict_item_id: string | null;
  conflict_kind: string;
  curation_item_id: string;
  external_item_id: string;
};

type Envelope<T> = { data: T; meta: { page?: { next_cursor: string | null } } };

type QuarantinePreview = {
  items: QuarantineItem[];
  target_collection_revision: string | null;
};

const COLLECTION_ID = process.env.E2E_QUARANTINE_COLLECTION_ID ?? "";
const EXECUTE_WRITE = process.env.E2E_QUARANTINE_WRITE === "1";
const CONFLICT_ITEM_ID = process.env.E2E_QUARANTINE_EXPECT_CONFLICT_ITEM_ID ?? "";
const FLOW_TIMEOUT = 120_000;

// 파괴적 spec은 직렬 + 무재시도 (cache-target-streams-isolated 관용).
test.describe.configure({ mode: "serial" });

async function fetchBffJson<T>(
  page: import("@playwright/test").Page,
  pathname: string,
): Promise<T> {
  const response = await page.request.get(pathname);
  expect(response.ok(), `${pathname} -> ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

test.describe("curation quarantine 재분류 (격리 clone 전용)", () => {
  test.skip(COLLECTION_ID === "", "E2E_QUARANTINE_COLLECTION_ID 미설정 — 합성 격리 필요");

  test("격리 목록이 marker·원본 병렬 정보를 내려준다 (ADR-048 봉투)", async ({ page }) => {
    test.setTimeout(FLOW_TIMEOUT);
    const body = await fetchBffJson<Envelope<{ items: QuarantineCollection[] }>>(
      page,
      "/api/proxy/v1/admin/curations/quarantine?page_size=50",
    );
    // meta.page.next_cursor는 항상 키로 존재해야 한다 (소진 시 null) — ADR-048 §12.
    expect(body.meta.page).toBeDefined();
    expect("next_cursor" in (body.meta.page ?? {})).toBe(true);

    const target = body.data.items.find(
      (item) => item.collection_id === COLLECTION_ID,
    );
    expect(target, "합성 격리 collection이 목록에 없다").toBeDefined();
    expect(target?.marker_intact).toBe(true);
    expect(target?.title).toContain("[0065 격리]");
  });

  test("conflict preview가 합성 충돌을 이름으로 지목한다", async ({ page }) => {
    test.setTimeout(FLOW_TIMEOUT);
    const body = await fetchBffJson<
      Envelope<{ items: QuarantineItem[]; target_missing: boolean }>
    >(
      page,
      `/api/proxy/v1/admin/curations/quarantine/${COLLECTION_ID}/items?page_size=200`,
    );
    expect(body.data.items.length).toBeGreaterThan(0);

    if (CONFLICT_ITEM_ID !== "") {
      const conflicted = body.data.items.find(
        (item) => item.curation_item_id === CONFLICT_ITEM_ID,
      );
      expect(conflicted, "충돌 합성 item이 preview에 없다").toBeDefined();
      expect([
        "component_identity_conflict",
        "active_source_feature_conflict",
      ]).toContain(conflicted?.conflict_kind);
      expect(conflicted?.conflict_item_id).not.toBeNull();
    }
  });

  test("move 재분류가 원자적으로 적용되고 빈 격리 collection이 정리된다", async (
    { page },
    testInfo,
  ) => {
    test.skip(!EXECUTE_WRITE, "E2E_QUARANTINE_WRITE=1 없음 — 파괴 스텝 생략");
    test.setTimeout(FLOW_TIMEOUT);
    // 파괴적 스텝은 직렬 + 무재시도에서만 (cache-target-streams-isolated 관용).
    expect(testInfo.config.workers).toBe(1);
    expect(testInfo.project.retries).toBe(0);

    const collections = await fetchBffJson<
      Envelope<{ items: QuarantineCollection[] }>
    >(page, "/api/proxy/v1/admin/curations/quarantine?page_size=50");
    const quarantine = collections.data.items.find(
      (item) => item.collection_id === COLLECTION_ID,
    );
    expect(quarantine, "합성 격리 collection이 목록에 없다").toBeDefined();
    const preview = await fetchBffJson<Envelope<QuarantinePreview>>(
      page,
      `/api/proxy/v1/admin/curations/quarantine/${COLLECTION_ID}/items?page_size=200`,
    );
    expect(preview.data.target_collection_revision).not.toBeNull();
    const movable = preview.data.items.filter(
      (item) => item.conflict_kind === "movable",
    );
    test.skip(movable.length === 0, "movable item이 없다 — 합성 상태 확인 필요");

    const idempotencyKey = crypto.randomUUID();
    const requestBody = {
      action: "move",
      item_ids: movable.map((item) => item.curation_item_id),
      target_collection_id: null,
      target_collection_revision: preview.data.target_collection_revision,
    };
    const first = await page.request.post(
      `/api/proxy/v1/admin/curations/quarantine/${COLLECTION_ID}/reclassify`,
      {
        data: requestBody,
        headers: {
          "Idempotency-Key": idempotencyKey,
          "If-Match": quarantine?.command_etag ?? "",
        },
      },
    );
    expect(first.status(), await first.text()).toBe(200);
    const etag = first.headers()["etag"];
    expect(etag).toMatch(/^"sha256:[0-9a-f]{64}"$/);
    const firstBody = (await first.json()) as Envelope<{
      moved_item_ids: string[];
      quarantine_collection_deleted: boolean;
    }>;
    expect(firstBody.data.moved_item_ids.length).toBe(movable.length);

    // terminal replay — 같은 key + 같은 body는 저장된 결과를 그대로 돌려준다.
    const replay = await page.request.post(
      `/api/proxy/v1/admin/curations/quarantine/${COLLECTION_ID}/reclassify`,
      {
        data: requestBody,
        headers: {
          "Idempotency-Key": idempotencyKey,
          "If-Match": quarantine?.command_etag ?? "",
        },
      },
    );
    expect(replay.status()).toBe(200);
    expect(replay.headers()["idempotency-replayed"]).toBe("true");
    expect(replay.headers()["etag"]).toBe(etag);

    // 전량 이동이었다면 격리 collection 자체가 사라졌어야 한다.
    if (firstBody.data.quarantine_collection_deleted) {
      const after = await fetchBffJson<Envelope<{ items: QuarantineCollection[] }>>(
        page,
        "/api/proxy/v1/admin/curations/quarantine?page_size=50",
      );
      expect(
        after.data.items.find((item) => item.collection_id === COLLECTION_ID),
      ).toBeUndefined();
    }
  });
});
