import { expect, test, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

type OfflineUploadWriteResponse =
  components["schemas"]["OfflineUploadWriteResponse"];
type OfflineUploadDetailResponse =
  components["schemas"]["OfflineUploadDetailResponse"];
type OfflineUploadDeleteResponse =
  components["schemas"]["OfflineUploadDeleteResponse"];
type OfflineUploadListResponse =
  components["schemas"]["OfflineUploadListResponse"];
type OpsDatasetsGridResponse = components["schemas"]["OpsDatasetsGridResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

// 병렬/재실행 충돌 방지를 위한 고유 RUN_ID. 파일 본문에 박아 checksum을 유일하게
// 만들어, 같은 canonical provider_dataset_id를 써도 dedup guard와 충돌하지 않는다.
const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const FILENAME = `e2e-${RUN_ID}.jsonl`;
// JSON/JSONL FeatureBundle(non-tabular)을 올린다 — create는 바이트만 저장하고
// 파싱하지 않으므로 내용은 비어 있지 않기만 하면 된다. RUN_ID로 checksum을 유일화한다.
// 비-tabular이므로 row 선택 시 preview/validation(S3 read+geo) 호출이 트리거되지 않는다.
const FILE_BODY = `{"kind":"place","name":"e2e offline upload","run_id":"${RUN_ID}"}\n`;

const EXECUTE_OFFLINE_UPLOAD_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" ||
  process.env.E2E_OFFLINE_UPLOAD_WRITE === "1";

// tag로 본문(=checksum)을 유일화한다. 같은 tag를 두 번 쓰면 동일 checksum →
// provider_dataset_id/scope/checksum 멱등 가드(409 OFFLINE_UPLOAD_DUPLICATE)를 트리거한다.
function fileBody(tag: string): string {
  return `{"kind":"place","name":"e2e offline upload ${tag}","run_id":"${RUN_ID}"}\n`;
}

function uploadFilename(tag: string): string {
  return `e2e-${RUN_ID}-${tag}.jsonl`;
}

test.describe.configure({ mode: "serial" });

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function isApiResponse(
  response: Response,
  method: string,
  path: string,
): boolean {
  return response.request().method() === method && apiPath(response) === path;
}

function listPath(): string {
  return "/v1/admin/offline-uploads";
}

function offlineUploadPath(uploadId: string): string {
  return `/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}`;
}

async function waitForApiResponse(
  page: Page,
  method: string,
  path: string,
): Promise<Response> {
  return page.waitForResponse(
    (response) => isApiResponse(response, method, decodeURIComponent(path)),
    { timeout: FLOW_TIMEOUT },
  );
}

async function browserFetch<T>(
  page: Page,
  path: string,
  options: { body?: unknown; method?: "GET" | "POST" | "PATCH" | "DELETE" } = {},
): Promise<BrowserFetchResult<T>> {
  return page.evaluate(
    async ({ body, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        credentials: "same-origin",
        cache: "no-store",
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text.length > 0 ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      return { body: parsed as T | null, status: response.status, text };
    },
    {
      body: options.body,
      method: options.method ?? "GET",
      path,
    },
  );
}

async function readWriteResponse(
  response: Response,
): Promise<OfflineUploadWriteResponse> {
  expect(response.status()).toBe(201);
  return (await response.json()) as OfflineUploadWriteResponse;
}

async function readDeleteResponse(
  response: Response,
): Promise<OfflineUploadDeleteResponse> {
  expect(response.status()).toBe(200);
  return (await response.json()) as OfflineUploadDeleteResponse;
}

async function fetchOfflineUpload(
  page: Page,
  uploadId: string,
): Promise<BrowserFetchResult<OfflineUploadDetailResponse>> {
  return browserFetch<OfflineUploadDetailResponse>(
    page,
    offlineUploadPath(uploadId),
  );
}

async function expectOfflineUploadsReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "오프라인 업로드" }),
  ).toBeVisible(T);
  await expect(page.getByTestId("offline-upload-file-input")).toBeVisible(T);
  await expect(page.getByLabel("offline upload status")).toBeVisible(T);
}

async function gotoOfflineUploads(page: Page): Promise<void> {
  await page.goto("/admin/offline-uploads");
  await expectOfflineUploadsReady(page);
}

async function deleteOfflineUploadByApi(
  page: Page,
  uploadId: string,
): Promise<void> {
  await browserFetch<OfflineUploadDeleteResponse>(page, offlineUploadPath(uploadId), {
    method: "DELETE",
  });
}

// POST 성공 응답에서 받은 upload_id만 best-effort로 지운다. 목록은
// provider_dataset_id 경계라 같은 dataset을 쓰는 다른 run을 절대 sweep하지 않는다.
async function deleteKnownOfflineUploads(
  page: Page,
  uploadIds: Iterable<string | null>,
): Promise<void> {
  for (const uploadId of uploadIds) {
    if (uploadId !== null) {
      await deleteOfflineUploadByApi(page, uploadId);
    }
  }
}

async function canonicalProviderDatasetId(page: Page): Promise<number> {
  const response = await browserFetch<OpsDatasetsGridResponse>(
    page,
    "/v1/ops/datasets",
  );
  expect(response.status).toBe(200);
  const row = response.body?.data.items.find(
    (item) => item.catalog_state === "canonical" && item.mutable,
  );
  expect(row, "offline upload live E2E에는 mutable canonical provider dataset이 필요합니다.").toBeDefined();
  return row?.provider_dataset_id as number;
}

// 업로드 폼(파일 input + canonical provider dataset ID/scope + submit)을 채운 뒤
// POST 응답을 그대로 돌려준다. 성공(201)/중복(409)/검증실패(422)를 호출부에서
// 분기하도록 status 단언은 하지 않는다(읽기는 readWriteResponse로).
async function submitUploadForm(
  page: Page,
  options: {
    body: string;
    filename: string;
    mimeType?: string;
    providerDatasetId: number;
  },
): Promise<Response> {
  await page.getByTestId("offline-upload-file-input").setInputFiles({
    buffer: Buffer.from(options.body),
    mimeType: options.mimeType ?? "application/x-ndjson",
    name: options.filename,
  });
  await page
    .getByLabel("provider dataset ID", { exact: true })
    .fill(String(options.providerDatasetId));
  await page.getByLabel("sync scope", { exact: true }).fill("default");

  const responsePromise = waitForApiResponse(page, "POST", listPath());
  await page.getByTestId("offline-upload-submit").click();
  return responsePromise;
}

// canonical provider dataset ID(+선택적 status)로 서버 목록을 직접 읽어
// backend 필터/정렬을 검증한다.
async function listUploadsByProviderDatasetId(
  page: Page,
  providerDatasetId: number,
  status?: string,
): Promise<OfflineUploadListResponse | null> {
  let path = `${listPath()}?provider_dataset_id=${providerDatasetId}&page_size=200`;
  if (status !== undefined) {
    path += `&status=${encodeURIComponent(status)}`;
  }
  const response = await browserFetch<OfflineUploadListResponse>(page, path);
  return response.body;
}

test.describe("/admin/offline-uploads live write workflow", () => {
  test("새 오프라인 업로드를 폼으로 생성, persist 확인, 목록/detail 반영, 삭제까지 실제 서비스에 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_OFFLINE_UPLOAD_WRITE,
      "E2E_OFFLINE_UPLOAD_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 offline upload write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let uploadId: string | null = null;
    let checksum: string | null = null;
    let providerDatasetId: number | null = null;
    let deleted = false;

    try {
      await test.step("업로드 폼으로 새 JSONL offline upload를 생성한다", async () => {
        await gotoOfflineUploads(page);

        await page.getByTestId("offline-upload-file-input").setInputFiles({
          buffer: Buffer.from(FILE_BODY),
          mimeType: "application/x-ndjson",
          name: FILENAME,
        });
        providerDatasetId = await canonicalProviderDatasetId(page);
        await page
          .getByLabel("provider dataset ID", { exact: true })
          .fill(String(providerDatasetId));
        await page.getByLabel("sync scope", { exact: true }).fill("default");

        const responsePromise = waitForApiResponse(
          page,
          "POST",
          listPath(),
        );
        await page.getByTestId("offline-upload-submit").click();
        const createResponse = await readWriteResponse(await responsePromise);

        uploadId = createResponse.data.upload_id;
        checksum = createResponse.data.checksum_sha256;
        expect(uploadId).toBeTruthy();
        expect(createResponse.data).toMatchObject({
          detected_format: "jsonl",
          original_filename: FILENAME,
          provider_dataset_id: providerDatasetId,
          status: "uploaded",
          storage_backend: "rustfs",
          sync_scope: "default",
        });

        // UI success alert.
        await expect(page.getByText("업로드 완료")).toBeVisible(T);
      });

      await test.step("API GET으로 업로드가 실제 persist 됐는지 확인한다", async () => {
        expect(uploadId).not.toBeNull();
        await expect
          .poll(async () => {
            const response = await fetchOfflineUpload(page, uploadId as string);
            return response.body?.data.status ?? `http:${response.status}`;
          }, T)
          .toBe("uploaded");

        const detail = await fetchOfflineUpload(page, uploadId as string);
        expect(detail.status).toBe(200);
        expect(detail.body?.data).toMatchObject({
          provider_dataset_id: providerDatasetId,
          upload_id: uploadId as string,
        });
      });

      await test.step("목록을 canonical ID로 필터하면 새 업로드 row가 상태/포맷과 함께 보인다", async () => {
        await page
          .getByLabel("provider dataset ID filter")
          .fill(String(providerDatasetId));

        const row = page.getByTestId("offline-upload-row");
        await expect(row).toHaveCount(1, T);
        await expect(row).toContainText(`#${providerDatasetId}`);
        // status badge는 statusLabel로 한글 렌더된다('uploaded'→'업로드됨'). status
        // <select>의 숨은 <option>은 영어 원문이므로 row scope으로 좁혀 한글 badge만 단언한다.
        await expect(row.getByText("업로드됨")).toBeVisible(T);
        await expect(row.getByText("jsonl", { exact: true })).toBeVisible(T);
        await expect(page.getByText("1 rows")).toBeVisible(T);
      });

      await test.step("row를 선택하면 detail 패널이 같은 업로드(checksum)를 반영한다", async () => {
        // 안전하게 되돌릴 수 있는 edit/process action이 없다(load=Dagster job 실행,
        // validate=CSV/TSV 전용 + S3 read/geo). 따라서 mutate 대신 row 선택 →
        // detail GET round-trip으로 presence를 검증한다. checksum(64-hex)은 detail
        // 패널 sha256 row에만 렌더되어 페이지에서 유일하므로 강한 reflection 단언이다.
        expect(checksum).not.toBeNull();
        await page.getByTestId("offline-upload-row").click();
        await expect(page.getByText(FILENAME).first()).toBeVisible(T);
        await expect(page.getByText(checksum as string).first()).toBeVisible(T);
      });

      await test.step("row 삭제 버튼으로 업로드를 삭제하고 백엔드/목록에서 사라진다", async () => {
        const row = page.getByTestId("offline-upload-row");
        const responsePromise = waitForApiResponse(
          page,
          "DELETE",
          offlineUploadPath(uploadId as string),
        );
        await row.getByTestId("offline-upload-delete").click();
        const deleteResponse = await readDeleteResponse(await responsePromise);
        expect(deleteResponse.data.upload_id).toBe(uploadId as string);
        deleted = true;

        await expect(page.getByText("업로드 삭제됨")).toBeVisible(T);

        // 백엔드 reflection: 단건 GET이 404로 떨어진다.
        await expect
          .poll(async () => {
            const response = await fetchOfflineUpload(page, uploadId as string);
            return response.status;
          }, T)
          .toBe(404);

        // UI reflection: canonical ID 필터가 유지되어 목록이 비고 empty 메시지가 뜬다.
        await expect(page.getByTestId("offline-upload-row")).toHaveCount(0, T);
        await expect(page.getByText("offline upload가 없습니다.")).toBeVisible(T);
      });
    } finally {
      // UI 삭제가 확정되지 않았으면(중간 실패 포함) 응답에서 받은 row만 정리한다.
      if (!deleted) {
        await deleteKnownOfflineUploads(page, [uploadId]);
      }
    }
  });

  test("같은 provider dataset으로 여러 업로드를 만들면 목록이 최신 생성순(created_at DESC)으로 정렬되고 canonical ID 필터가 정확히 격리한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_OFFLINE_UPLOAD_WRITE,
      "E2E_OFFLINE_UPLOAD_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 offline upload write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const tags = ["multi-1", "multi-2", "multi-3"];
    const createdIds: string[] = [];
    let providerDatasetId: number | null = null;

    try {
      await test.step("같은 provider dataset으로 3개의 JSONL 업로드를 순차 생성한다", async () => {
        await gotoOfflineUploads(page);
        providerDatasetId = await canonicalProviderDatasetId(page);
        for (const tag of tags) {
          const response = await submitUploadForm(page, {
            body: fileBody(tag),
            filename: uploadFilename(tag),
            providerDatasetId: providerDatasetId as number,
          });
          const created = await readWriteResponse(response);
          // provider 컬럼은 OfflineUploadRecord에서 삭제됐다(ADR-088 triple identity).
          // 업로드 격리는 아래 provider 필터 목록 단언이 계속 검증한다.
          expect(created.data.original_filename).toBe(uploadFilename(tag));
          expect(created.data.status).toBe("uploaded");
          createdIds.push(created.data.upload_id);
        }
        // 세 건 모두 서로 다른 upload_id(서버가 매번 새 uuid 발급).
        expect(new Set(createdIds).size).toBe(3);
      });

      await test.step("API 목록이 최신 생성 업로드를 먼저 반환한다(created_at DESC)", async () => {
        const body = await listUploadsByProviderDatasetId(
          page,
          providerDatasetId as number,
          "uploaded",
        );
        const items = body?.data.items ?? [];
        expect(items.map((item) => item.original_filename)).toEqual([
          uploadFilename("multi-3"),
          uploadFilename("multi-2"),
          uploadFilename("multi-1"),
        ]);
        // 정렬 키(생성순)와 우리가 만든 순서가 역순으로 일치한다.
        expect(items.map((item) => item.upload_id)).toEqual([
          createdIds[2],
          createdIds[1],
          createdIds[0],
        ]);
      });

      await test.step("UI 목록도 같은 순서로 3개 row를 렌더한다", async () => {
        await page
          .getByLabel("provider dataset ID filter")
          .fill(String(providerDatasetId));
        const rows = page.getByTestId("offline-upload-row");
        await expect(rows).toHaveCount(3, T);
        await expect(page.getByText("3 rows")).toBeVisible(T);
        await expect(rows.nth(0)).toContainText(uploadFilename("multi-3"));
        await expect(rows.nth(2)).toContainText(uploadFilename("multi-1"));
      });
    } finally {
      await deleteKnownOfflineUploads(page, createdIds);
    }
  });

  test("offline upload status 필터가 backend status 쿼리와 UI 목록 모두에서 라운드트립한다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_OFFLINE_UPLOAD_WRITE,
      "E2E_OFFLINE_UPLOAD_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 offline upload write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let uploadId: string | null = null;
    let providerDatasetId: number | null = null;

    try {
      await test.step("status 라운드트립 검증용 업로드 1건을 생성한다", async () => {
        await gotoOfflineUploads(page);
        providerDatasetId = await canonicalProviderDatasetId(page);
        const response = await submitUploadForm(page, {
          body: fileBody("status-1"),
          filename: uploadFilename("status-1"),
          providerDatasetId: providerDatasetId as number,
        });
        const created = await readWriteResponse(response);
        uploadId = created.data.upload_id;
        expect(created.data.status).toBe("uploaded");
      });

      await test.step("backend status 쿼리 파라미터가 실제로 필터링한다", async () => {
        // 일치하는 status(uploaded)는 우리 업로드를, 불일치 status(loaded)는 0건을 반환.
        const uploadedList = await listUploadsByProviderDatasetId(
          page,
          providerDatasetId as number,
          "uploaded",
        );
        expect((uploadedList?.data.items ?? []).map((item) => item.upload_id)).toEqual([
          uploadId,
        ]);
        const loadedList = await listUploadsByProviderDatasetId(
          page,
          providerDatasetId as number,
          "loaded",
        );
        expect(loadedList?.data.items ?? []).toHaveLength(0);
      });

      await test.step("UI status select를 바꾸면 목록이 backend 결과를 반영한다", async () => {
        await page
          .getByLabel("provider dataset ID filter")
          .fill(String(providerDatasetId));
        // 기본 status=uploaded → 우리 업로드 1건이 status badge(한글 '업로드됨')와 함께 보인다.
        await expect(page.getByTestId("offline-upload-row")).toHaveCount(1, T);
        await expect(page.getByText("1 rows")).toBeVisible(T);
        await expect(
          page.getByTestId("offline-upload-row").getByText("업로드됨"),
        ).toBeVisible(T);

        // loaded로 바꾸면 backend가 0건을 돌려줘 목록이 비고 empty 메시지가 뜬다.
        await page.getByLabel("offline upload status").selectOption("loaded");
        await expect(page.getByTestId("offline-upload-row")).toHaveCount(0, T);
        await expect(page.getByText("0 rows")).toBeVisible(T);
        await expect(page.getByText("offline upload가 없습니다.")).toBeVisible(T);

        // 다시 uploaded로 바꾸면 동일 업로드가 복귀한다.
        await page.getByLabel("offline upload status").selectOption("uploaded");
        await expect(page.getByTestId("offline-upload-row")).toHaveCount(1, T);
      });
    } finally {
      await deleteKnownOfflineUploads(page, [uploadId]);
    }
  });

  test("지원하지 않는 포맷 업로드는 422로 거절되고 UI에 실패가 표면화되며 아무것도 persist 되지 않는다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_OFFLINE_UPLOAD_WRITE,
      "E2E_OFFLINE_UPLOAD_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 offline upload write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);
    let providerDatasetId: number | null = null;

    await test.step(".txt 파일을 제출하면 서버가 422로 거절한다", async () => {
      await gotoOfflineUploads(page);
      providerDatasetId = await canonicalProviderDatasetId(page);
      // detected_format이 None이라 OFFLINE_UPLOAD_WRITEABLE_FORMATS(json/jsonl/csv/tsv)에
      // 없으므로 라우터가 본문을 읽기 전에 422로 거절한다.
      const response = await submitUploadForm(page, {
        body: "this is not a feature bundle\n",
        filename: `e2e-${RUN_ID}-invalid.txt`,
        mimeType: "text/plain",
        providerDatasetId: providerDatasetId as number,
      });
      expect(response.status()).toBe(422);

      // UI reflection: 업로드 실패 destructive alert.
      await expect(page.getByText("업로드 실패")).toBeVisible(T);
    });

    await test.step("거절된 파일명은 해당 canonical ID 목록에 남지 않는다", async () => {
      const body = await listUploadsByProviderDatasetId(
        page,
        providerDatasetId as number,
      );
      expect(
        (body?.data.items ?? []).some(
          (item) => item.original_filename === `e2e-${RUN_ID}-invalid.txt`,
        ),
      ).toBe(false);
    });
  });

  test("중복 checksum 업로드는 409로 막히고, 삭제로 가드가 풀린 뒤 같은 내용을 새 upload_id로 재생성할 수 있다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_OFFLINE_UPLOAD_WRITE,
      "E2E_OFFLINE_UPLOAD_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 offline upload write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    // 같은 tag → 같은 본문 → 같은 checksum으로 멱등 가드를 유발/검증한다.
    const dupBody = fileBody("dup");
    const dupFilename = uploadFilename("dup");
    let firstUploadId: string | null = null;
    let firstChecksum: string | null = null;
    let secondUploadId: string | null = null;
    let providerDatasetId: number | null = null;

    try {
      await test.step("첫 업로드를 생성한다", async () => {
        await gotoOfflineUploads(page);
        providerDatasetId = await canonicalProviderDatasetId(page);
        const response = await submitUploadForm(page, {
          body: dupBody,
          filename: dupFilename,
          providerDatasetId: providerDatasetId as number,
        });
        const created = await readWriteResponse(response);
        firstUploadId = created.data.upload_id;
        firstChecksum = created.data.checksum_sha256;
        expect(firstChecksum).toBeTruthy();
      });

      await test.step("동일 provider dataset/scope/checksum 재업로드는 409 OFFLINE_UPLOAD_DUPLICATE", async () => {
        const response = await submitUploadForm(page, {
          body: dupBody,
          filename: dupFilename,
          providerDatasetId: providerDatasetId as number,
        });
        expect(response.status()).toBe(409);
        expect(await response.text()).toContain("OFFLINE_UPLOAD_DUPLICATE");
        await expect(page.getByText("업로드 실패")).toBeVisible(T);
      });

      await test.step("중복은 persist 되지 않아 backend에는 여전히 첫 업로드 1건만 있다", async () => {
        const body = await listUploadsByProviderDatasetId(
          page,
          providerDatasetId as number,
          "uploaded",
        );
        expect((body?.data.items ?? []).map((item) => item.upload_id)).toEqual([
          firstUploadId,
        ]);
      });

      await test.step("row 삭제 버튼으로 첫 업로드를 제거한다", async () => {
        await page
          .getByLabel("provider dataset ID filter")
          .fill(String(providerDatasetId));
        const row = page.getByTestId("offline-upload-row");
        await expect(row).toHaveCount(1, T);

        // 현재 컴포넌트는 window.confirm 없이 바로 mutate 하므로 dialog가 뜨지 않는다.
        // 미래에 확인 dialog가 추가되어도 막히지 않도록 방어적으로 accept 핸들러만 건다.
        page.once("dialog", (dialog) => void dialog.accept());
        const responsePromise = waitForApiResponse(
          page,
          "DELETE",
          offlineUploadPath(firstUploadId as string),
        );
        await row.getByTestId("offline-upload-delete").click();
        const deleteResponse = await readDeleteResponse(await responsePromise);
        expect(deleteResponse.data.upload_id).toBe(firstUploadId as string);
        await expect(page.getByText("업로드 삭제됨")).toBeVisible(T);

        // 백엔드/UI reflection: 단건 GET 404 + 목록 비움.
        await expect
          .poll(async () => {
            const detail = await fetchOfflineUpload(page, firstUploadId as string);
            return detail.status;
          }, T)
          .toBe(404);
        await expect(page.getByTestId("offline-upload-row")).toHaveCount(0, T);
        await expect(page.getByText("offline upload가 없습니다.")).toBeVisible(T);
      });

      await test.step("삭제로 멱등 가드가 풀려 같은 내용을 새 upload_id로 다시 만들 수 있다", async () => {
        const response = await submitUploadForm(page, {
          body: dupBody,
          filename: dupFilename,
          providerDatasetId: providerDatasetId as number,
        });
        const recreated = await readWriteResponse(response);
        secondUploadId = recreated.data.upload_id;
        // id 재사용이 아니라 새 uuid가 발급되고, 내용(checksum)은 동일하다.
        expect(secondUploadId).not.toBe(firstUploadId);
        expect(recreated.data.checksum_sha256).toBe(firstChecksum);

        // 백엔드 reflection: 새 업로드가 uploaded 상태로 persist.
        const detail = await fetchOfflineUpload(page, secondUploadId as string);
        expect(detail.status).toBe(200);
        expect(detail.body?.data.status).toBe("uploaded");

        // UI reflection: canonical ID 필터가 걸린 목록에 1건이 다시 보인다.
        await expect(page.getByTestId("offline-upload-row")).toHaveCount(1, T);
        await expect(page.getByTestId("offline-upload-row")).toContainText(dupFilename);

        // backend 목록도 재생성본 1건만 반환.
        const body = await listUploadsByProviderDatasetId(
          page,
          providerDatasetId as number,
          "uploaded",
        );
        expect((body?.data.items ?? []).map((item) => item.upload_id)).toEqual([
          secondUploadId,
        ]);
      });
    } finally {
      await deleteKnownOfflineUploads(page, [firstUploadId, secondUploadId]);
    }
  });
});
