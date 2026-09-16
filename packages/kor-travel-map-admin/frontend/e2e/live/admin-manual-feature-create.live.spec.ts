import { expect, test } from "@playwright/test";

/**
 * T-VN-M01/M02 — admin 수동 Feature 생성 route의 live cutover gate와
 * provenance 불변 계약의 live acceptance.
 *
 * M01: kill-switch가 켜진 스택에서 `/admin/features/new` UI 폼으로 실제 생성이
 * 완주하고(BFF가 전용 token을 부착), 같은 identity 재제출이 exact-conflict로
 * fail-close한다.
 * M02: creation-provenance reader가 opaque `feature_id`와 별도 `feature_uuid`를
 * 최상위에 함께 반환하고, immutable claim의 UUID가 최상위 `feature_uuid`와
 * 일치하며, origin이 단건 admin 경로의 principal/role 계약을 정확히 싣는다.
 *
 * 쓰기 스펙 opt-in: E2E_MANUAL_CREATE_WRITE=1.
 *
 * **아직 격리 스택 전용이고, 이유는 cleanup이 없기 때문이다.** 이 spec은 Feature를
 * 만들고 **지우지 않는다** — `feature.purge_manual_feature` 프로시저는 #306으로
 * 생겼지만 **HTTP로 노출돼 있지 않아**(API 라우터에 없다) spec이 부를 길이 없다
 * (2026-09-16 실측). 그래서 지금 prod에서 돌리면 지울 수 없는 행이 남는다 —
 * 같은 형태가 `T-VN-D2-RESIDUE`로 이미 열려 있다.
 *
 * actor는 더 이상 막는 이유가 아니다: 종전에는 `"e2e-admin"` 리터럴 때문에 prod에서
 * 구조적으로 실패했는데, 아래 단언을 환경에서 유도하도록 고쳤다.
 */

type Envelope<T> = { data: T };

const FLOW_TIMEOUT = 60_000;
const EXECUTE = process.env.E2E_MANUAL_CREATE_WRITE === "1";

test.describe("M01/M02 admin 수동 Feature 생성 live acceptance", () => {
  test("UI 생성 → provenance 계약 → exact-conflict fail-close", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE,
      "쓰기 스펙 — 격리 스택에서 E2E_MANUAL_CREATE_WRITE=1 명시 opt-in이 필요합니다.",
    );
    test.setTimeout(4 * 60_000);
    const suffix = Date.now().toString(36);
    // claim identity는 (kind, name_key, lon_e6, lat_e6)이다 — 이름과 좌표 소수부를
    // run마다 흔들어 이전 run의 claim과 충돌하지 않게 한다.
    const jitter = (Date.now() % 9000) + 100;
    const lon = `127.0${jitter}`;
    const lat = `37.50${jitter % 900}`;
    const name = `M01 live 수동 생성 ${suffix}`;

    const fill = async () => {
      await page.goto("/admin/features/new");
      await page
        .getByRole("textbox", { name: "create name", exact: true })
        .fill(name);
      await page
        .getByRole("textbox", { name: "사유", exact: true })
        .fill("M01 live cutover gate");
      await page.getByRole("textbox", { name: "경도", exact: true }).fill(lon);
      await page.getByRole("textbox", { name: "위도", exact: true }).fill(lat);
    };

    // ── M01: 생성 완주 ───────────────────────────────────────────────────
    await fill();
    const createResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/proxy/v1/admin/features") &&
        response.request().method() === "POST",
      { timeout: FLOW_TIMEOUT },
    );
    await page.getByRole("button", { name: "Feature 생성" }).click();
    const created = await createResponse;
    expect(created.status()).toBe(201);
    // create 응답의 feature_id는 T-VN-32C 응답 규약대로 UUID 정본이다.
    const createdBody = (await created.json()) as Envelope<{
      feature_id: string;
    }>;
    const featureUuid = createdBody.data.feature_id;
    expect(featureUuid).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );

    const detail = await page.request.get(
      `/api/proxy/v1/admin/features/${featureUuid}`,
    );
    expect(detail.status()).toBe(200);
    const detailBody = (await detail.json()) as Envelope<{
      feature: { name: string };
    }>;
    expect(detailBody.data.feature.name).toBe(name);

    // ── M02: provenance reader 계약 ─────────────────────────────────────
    const provenance = await page.request.get(
      `/api/proxy/v1/admin/features/${featureUuid}/creation-provenance`,
    );
    expect(provenance.status()).toBe(200);
    const provenanceBody = (await provenance.json()) as Envelope<{
      feature_id: string;
      feature_uuid: string;
      claim: { feature_id: string; claim_basis: string } | null;
      origin: {
        origin_kind: string;
        creator_principal_id: string;
        invoker_role: string;
        procedure_definer: string;
        created_by_actor: string;
      };
    }>;
    const data = provenanceBody.data;
    // opaque feature_id와 별도 feature_uuid를 최상위에 함께 반환한다.
    expect(data.feature_uuid).toBe(featureUuid);
    expect(data.feature_id).toBeTruthy();
    // immutable claim의 UUID는 최상위 feature_uuid와 일치해야 한다(fail-close 계약).
    expect(data.claim).not.toBeNull();
    expect(data.claim?.feature_id).toBe(featureUuid);
    // 단건 admin 경로의 origin 계약 — import child와 구분되는 principal이다(F7).
    expect(data.origin.origin_kind).toBe("manual_admin");
    expect(data.origin.creator_principal_id).toBe(
      "admin-ui-bff.manual-feature-create.v1",
    );
    expect(data.origin.invoker_role).toBe("ktm_feature_api_runtime");
    // **로그인한 주체가 provenance까지 실려 오는가** — 그 값이 무엇인지가 아니다.
    // 종전에는 `"e2e-admin"`을 리터럴로 박아 두어 **환경이 바뀌면 부러졌다**: actor는
    // BFF의 `adminUsernameFromEnv()`(→ `ADMIN_USERNAME`, 기본 `admin`)에서 나와
    // `X-Kor-Travel-Map-Actor` 헤더 → 도메인 커맨드 → `created_by_actor`로 간다.
    // prod는 그 값이 `admin`이라 이 단언 하나 때문에 구조적으로 실패했다(2026-09-16
    // 실측). 저장소의 기존 관용구(`ops-c7-read-auth.live.spec.ts`)와 같은 형태로
    // 환경에서 유도한다 — 계약을 결박하고 그때의 값은 결박하지 않는다.
    expect(data.origin.created_by_actor).toBe(
      process.env.E2E_ADMIN_USERNAME ?? "admin",
    );

    // ── M01: 같은 identity 재제출은 exact-conflict fail-close ───────────
    await fill();
    const duplicateResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/proxy/v1/admin/features") &&
        response.request().method() === "POST",
      { timeout: FLOW_TIMEOUT },
    );
    await page.getByRole("button", { name: "Feature 생성" }).click();
    const duplicate = await duplicateResponse;
    expect(duplicate.status()).toBe(409);
  });
});
