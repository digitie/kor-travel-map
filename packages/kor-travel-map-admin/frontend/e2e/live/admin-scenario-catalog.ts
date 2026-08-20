import * as F from "./_fixtures";

export type AdminLiveScenarioRisk =
  | "read"
  | "write"
  | "destructive"
  | "cross_surface";

export type AdminLiveScenarioMode =
  | "catalog"
  | "live_smoke"
  | "live_write";

export type AdminWriteApiMethod = "POST" | "PATCH" | "PUT" | "DELETE";
export type AdminWriteApiRisk = Extract<
  AdminLiveScenarioRisk,
  "write" | "destructive"
>;

export type AdminWriteApi = {
  method: AdminWriteApiMethod;
  path: string;
  risk: AdminWriteApiRisk;
};

export type AdminSurface = {
  id: string;
  route: string;
  readyHeading: string;
  readApis: readonly string[];
  writeApis: readonly AdminWriteApi[];
  reflectedSurfaces: readonly string[];
};

export type AdminLiveScenario = {
  id: string;
  surface: string;
  route: string;
  mode: AdminLiveScenarioMode;
  risk: AdminLiveScenarioRisk;
  uiAction: string;
  apiExpectation: string;
  reflectedSurface: string;
};

const VIEWPORTS = [
  "desktop-1280",
  "tablet-768",
  "mobile-390",
] as const;
const ORDERS = ["asc", "desc"] as const;
const FEATURE_STATE_TUPLES = [
  ["active", "draft", "valid"],
  ["active", "draft", "quarantined"],
  ["active", "published", "valid"],
  ["active", "published", "quarantined"],
  ["active", "suppressed", "valid"],
  ["active", "suppressed", "quarantined"],
  ["retired", "suppressed", "valid"],
  ["retired", "suppressed", "quarantined"],
] as const;
const LOG_TABS = ["system", "api"] as const;
const LOG_LEVELS = ["all", "info", "warning", "error"] as const;
const REVIEW_STATUSES = [
  "all",
  "pending",
  "accepted",
  "rejected",
  "merged",
] as const;

function writeApi(
  method: AdminWriteApiMethod,
  path: string,
  risk: AdminWriteApiRisk = "write",
): AdminWriteApi {
  return { method, path, risk };
}

export const ADMIN_SURFACES: readonly AdminSurface[] = [
  {
    id: "home",
    route: "/",
    readyHeading: "운영 홈",
    readApis: [
      "/v1/ops/metrics",
      "/v1/ops/pipeline/overview",
      "/v1/ops/pipeline/executions",
      "/v1/admin/features/dedup-reviews",
    ],
    writeApis: [],
    reflectedSurfaces: ["/ops/pipeline", "/ops/datasets"],
  },
  {
    id: "pipeline",
    route: "/ops/pipeline",
    readyHeading: "파이프라인",
    readApis: [
      "/v1/ops/pipeline/overview",
      "/v1/ops/pipeline/executions",
      "/v1/ops/pipeline/executions/{kind}/{execution_id}",
      "/v1/ops/pipeline/events",
      "/v1/ops/pipeline/dagster-runs",
      "/v1/ops/pipeline/dagster-runs/{run_id}",
      "/v1/ops/pipeline/schedules",
      "/v1/ops/datasets",
      "/v1/ops/pipeline/prechecks/mois-source-sync",
    ],
    writeApis: [
      writeApi("POST", "/v1/ops/pipeline/requests"),
      writeApi("POST", "/v1/ops/pipeline/requests/preview"),
      writeApi("POST", "/v1/ops/pipeline/requests/{request_id}/run-now"),
      writeApi(
        "POST",
        "/v1/ops/pipeline/executions/{kind}/{execution_id}/cancel",
      ),
      writeApi("PATCH", "/v1/ops/pipeline/schedules/{schedule_name}"),
      writeApi(
        "POST",
        "/v1/ops/pipeline/schedules/{schedule_name}/commands",
      ),
      writeApi(
        "POST",
        "/v1/ops/pipeline/schedules/{schedule_name}/claims/{command_id}/resolve",
      ),
    ],
    reflectedSurfaces: ["/ops/datasets", "/features", "/ops/logs"],
  },
  {
    id: "datasets",
    route: "/ops/datasets",
    readyHeading: "데이터셋",
    readApis: [
      "/v1/ops/datasets",
      // ADR-088: detail은 canonical id 경로다(`/detail` 자연키 라우트는 삭제됐다).
      "/v1/ops/datasets/{provider_dataset_id}",
      "/v1/ops/pipeline/executions",
    ],
    writeApis: [
      writeApi("PUT", "/v1/ops/datasets/refresh-policy"),
      writeApi("POST", "/v1/ops/datasets/{provider_dataset_id}/preview"),
      writeApi("POST", "/v1/ops/pipeline/requests"),
    ],
    reflectedSurfaces: ["/ops/pipeline", "/features/{feature_id}"],
  },
  {
    id: "features-map",
    route: "/features",
    readyHeading: "Feature 지도",
    readApis: [
      "/v1/admin/features/in-bounds",
      "/v1/admin/features/{feature_id}",
      "/v1/admin/features/{feature_id}/weather",
      "/v1/admin/features/{feature_id}/price",
      "/v1/ops/datasets",
    ],
    writeApis: [],
    reflectedSurfaces: ["/admin/features", "/features/{feature_id}"],
  },
  {
    id: "feature-detail",
    route: "/features/{feature_id}",
    readyHeading: "Feature 상세",
    readApis: [
      "/v1/admin/features/{feature_id}",
      "/v1/admin/features/{feature_id}/weather",
      "/v1/admin/features/{feature_id}/price",
      "/v1/features/nearby",
    ],
    writeApis: [],
    reflectedSurfaces: ["/features", "/admin/features", "/ops/datasets"],
  },
  {
    id: "admin-features",
    route: "/admin/features",
    readyHeading: "Feature 목록",
    readApis: [
      "/v1/admin/features",
      "/v1/admin/features/{feature_id}",
      "/v1/admin/features/{feature_id}/revision",
      "/v1/admin/features/{feature_id}/state/transitions",
      "/v1/features/{feature_id}",
      "/v1/ops/datasets",
    ],
    writeApis: [
      writeApi("PATCH", "/v1/admin/features/{feature_id}/state"),
      writeApi("POST", "/v1/admin/features/{feature_id}/state/reactivate"),
      writeApi("PATCH", "/v1/admin/features/{feature_id}"),
      writeApi("DELETE", "/v1/admin/features/{feature_id}", "destructive"),
    ],
    reflectedSurfaces: [
      "/features",
      "/features/{feature_id}",
      "/ops/datasets",
    ],
  },
  // T-VN-36(0104)이 whole-row change-request/review 모델을 제거했다. 두 surface는
  // 라우트도 API도 없으므로 카탈로그에서 뺀다 — 남겨두면 카탈로그 spec이 surface마다
  // 발행하는 live_smoke 시나리오가 없는 라우트로 이동해 실패한다.
  {
    id: "new-feature",
    route: "/admin/features/new",
    readyHeading: "새 Feature",
    readApis: ["/v1/features/nearby"],
    writeApis: [writeApi("POST", "/v1/admin/features")],
    reflectedSurfaces: [
      "/admin/features/change-requests",
      "/admin/features",
      "/features/{feature_id}",
    ],
  },
  {
    id: "curated-features",
    route: "/admin/features/curated",
    readyHeading: "큐레이션 관리",
    readApis: [
      "/v1/admin/curated-source-rules",
      "/v1/admin/curated-sources",
      "/v1/admin/curated-themes",
      "/v1/admin/curations/quarantine",
      "/v1/admin/curations/quarantine/{collection_id}/items",
    ],
    // T-VN-40C: legacy `curated_features` API(list/detail/write, detail-snapshot)는
    // 표와 함께 물리 제거됐다. 이 surface의 read/write 계약은 canonical
    // curated-source-rules / curations quarantine 뿐이고, feature 단위 편집은
    // `curation-collections` surface의 collection/item command가 정본이다.
    writeApis: [
      writeApi("PATCH", "/v1/admin/curated-source-rules/{rule_id}"),
      writeApi(
        "POST",
        "/v1/admin/curations/quarantine/{collection_id}/reclassify",
      ),
    ],
    reflectedSurfaces: ["/ops/pipeline"],
  },
  {
    id: "issues",
    route: "/admin/issues",
    readyHeading: "이슈",
    readApis: ["/v1/admin/issues", "/v1/admin/issues/{issue_id}"],
    writeApis: [writeApi("PATCH", "/v1/admin/issues/{issue_id}")],
    reflectedSurfaces: ["/features/{feature_id}", "/ops/consistency"],
  },
  {
    id: "consistency",
    route: "/ops/consistency",
    readyHeading: "정합성 점검",
    readApis: [
      "/v1/ops/metrics",
      "/v1/ops/consistency/reports",
      "/v1/ops/consistency/issues",
    ],
    writeApis: [],
    reflectedSurfaces: ["/admin/issues", "/ops/pipeline"],
  },
  {
    id: "logs",
    route: "/ops/logs",
    readyHeading: "운영 로그",
    readApis: [
      "/v1/ops/system-logs",
      "/v1/ops/api-call-logs",
    ],
    writeApis: [],
    reflectedSurfaces: ["/ops/pipeline", "/admin/settings"],
  },
  {
    id: "dedup-reviews",
    route: "/admin/features/dedup-reviews",
    readyHeading: "중복 검토",
    readApis: ["/v1/admin/features/dedup-reviews", "/v1/admin/features/dedup-reviews/{review_id}"],
    writeApis: [writeApi("PATCH", "/v1/admin/features/dedup-reviews/{review_id}")],
    reflectedSurfaces: ["/admin/features", "/features/{feature_id}"],
  },
  {
    id: "enrichment-reviews",
    route: "/admin/features/enrichment-reviews",
    readyHeading: "보강 검토",
    readApis: [
      "/v1/admin/features/enrichment-reviews",
      "/v1/admin/features/enrichment-reviews/{review_id}",
    ],
    writeApis: [writeApi("PATCH", "/v1/admin/features/enrichment-reviews/{review_id}")],
    reflectedSurfaces: ["/admin/features", "/features/{feature_id}"],
  },
  {
    id: "poi-cache-targets",
    route: "/admin/poi-cache-targets",
    readyHeading: "POI 캐시 대상",
    readApis: ["/v1/admin/poi-cache-targets", "/v1/features/nearby/by-target"],
    writeApis: [
      writeApi(
        "PUT",
        "/v1/admin/poi-cache-targets/{external_system}/{target_key}",
      ),
      writeApi(
        "DELETE",
        "/v1/admin/poi-cache-targets/{external_system}/{target_key}",
        "destructive",
      ),
      writeApi("POST", "/v1/ops/pipeline/requests"),
    ],
    reflectedSurfaces: ["/features", "/ops/pipeline"],
  },
  {
    id: "offline-uploads",
    route: "/admin/offline-uploads",
    readyHeading: "오프라인 업로드",
    readApis: [
      "/v1/admin/offline-uploads",
      "/v1/admin/offline-uploads/{upload_id}/preview",
      "/v1/admin/offline-uploads/{upload_id}/validation",
      "/v1/ops/datasets",
    ],
    writeApis: [
      writeApi("POST", "/v1/admin/offline-uploads"),
      writeApi("POST", "/v1/admin/offline-uploads/{upload_id}/validate"),
      writeApi("POST", "/v1/admin/offline-uploads/{upload_id}/load"),
      writeApi(
        "DELETE",
        "/v1/admin/offline-uploads/{upload_id}",
        "destructive",
      ),
    ],
    reflectedSurfaces: ["/ops/pipeline", "/ops/logs"],
  },
  {
    id: "backups",
    route: "/admin/backups",
    readyHeading: "백업",
    readApis: ["/v1/admin/backups", "/v1/admin/backups/{backup_id}"],
    writeApis: [
      writeApi("POST", "/v1/admin/backups"),
      writeApi("DELETE", "/v1/admin/backups/{backup_id}", "destructive"),
      writeApi("POST", "/v1/admin/restore/{backup_id}", "destructive"),
      writeApi("POST", "/v1/admin/restore/{backup_id}/swap", "destructive"),
    ],
    reflectedSurfaces: ["/ops/logs", "/"],
  },
  {
    id: "files",
    route: "/admin/files",
    readyHeading: "파일 관리",
    readApis: [
      "/v1/admin/files",
      "/v1/admin/files/summary",
      "/v1/admin/files/{file_id}",
      "/v1/admin/files/{file_id}/events",
    ],
    writeApis: [
      writeApi("POST", "/v1/admin/files/rescan"),
      writeApi("POST", "/v1/admin/files/{file_id}/purge", "destructive"),
    ],
    reflectedSurfaces: ["/ops/pipeline", "/admin/offline-uploads"],
  },
  {
    id: "settings",
    route: "/admin/settings",
    readyHeading: "설정",
    readApis: ["/v1/admin/public-api-keys", "/v1/admin/auth-events"],
    writeApis: [
      writeApi("POST", "/v1/admin/public-api-keys"),
      writeApi("POST", "/v1/admin/public-api-keys/{public_api_key_id}/revoke"),
      writeApi("POST", "/v1/admin/auth-events"),
    ],
    reflectedSurfaces: ["/admin/settings", "/ops/logs"],
  },
];

function addScenario(
  scenarios: AdminLiveScenario[],
  scenario: Omit<AdminLiveScenario, "id"> & { idParts: readonly string[] },
): void {
  const id = scenario.idParts
    .map((part) => part.replace(/[^0-9A-Za-z가-힣_.:/=-]+/g, "-"))
    .join("__");
  scenarios.push({
    apiExpectation: scenario.apiExpectation,
    id,
    mode: scenario.mode,
    reflectedSurface: scenario.reflectedSurface,
    risk: scenario.risk,
    route: scenario.route,
    surface: scenario.surface,
    uiAction: scenario.uiAction,
  });
}

export function buildAdminLiveScenarioCatalog(): AdminLiveScenario[] {
  const scenarios: AdminLiveScenario[] = [];
  const searchTerms = F.SEARCH_TERMS.slice(0, 16);
  const kinds = F.KINDS.slice(0, 7);
  const pageSizes = F.PAGE_SIZES.slice(0, 4);
  const categories = F.CATEGORY_CODES.slice(0, 40);
  const featureIds = F.FEATURE_IDS.slice(0, 120);
  const curationItemIds = F.CURATION_ITEM_IDS.slice(0, 40);

  for (const surface of ADMIN_SURFACES) {
    for (const viewport of VIEWPORTS) {
      addScenario(scenarios, {
        apiExpectation: surface.readApis.join(", "),
        idParts: ["route", surface.id, viewport],
        mode: "live_smoke",
        reflectedSurface: surface.reflectedSurfaces[0] ?? surface.route,
        risk: "read",
        route: surface.route,
        surface: surface.id,
        uiAction: `load ${surface.route} at ${viewport}`,
      });
    }
    for (const writeApi of surface.writeApis) {
      addScenario(scenarios, {
        apiExpectation: `${writeApi.method} ${writeApi.path}`,
        idParts: ["write-contract", surface.id, writeApi.method, writeApi.path],
        mode: "catalog",
        reflectedSurface: surface.reflectedSurfaces[0] ?? surface.route,
        risk: writeApi.risk,
        route: surface.route,
        surface: surface.id,
        uiAction: `write action is reflected after ${writeApi.method} ${writeApi.path}`,
      });
    }
  }

  for (const term of searchTerms) {
    for (const kind of kinds) {
      for (const [lifecycle, publication, quality] of FEATURE_STATE_TUPLES) {
        for (const size of pageSizes) {
          for (const order of ORDERS) {
            addScenario(scenarios, {
              apiExpectation:
                "/v1/admin/features q/kind/lifecycle_state/publication_state/quality_state/page_size/order query",
              idParts: [
                "admin-features",
                term,
                kind,
                lifecycle,
                publication,
                quality,
                String(size),
                order,
              ],
              mode: "catalog",
              reflectedSurface: "/features",
              risk: "cross_surface",
              route: "/admin/features",
              surface: "admin-features",
              uiAction: `search=${term}, kind=${kind}, lifecycle=${lifecycle}, publication=${publication}, quality=${quality}, size=${size}, order=${order}`,
            });
          }
        }
      }
    }
  }

  for (const [placeName, lon, lat, zoom] of F.MAP_VIEWS) {
    for (const kind of kinds) {
      for (const size of pageSizes) {
        for (const viewport of VIEWPORTS) {
          addScenario(scenarios, {
            apiExpectation:
              "/v1/admin/features/in-bounds query, then admin detail parity",
            idParts: [
              "features-map",
              String(placeName),
              kind,
              String(size),
              viewport,
            ],
            mode: "catalog",
            reflectedSurface: "/admin/features",
            risk: "cross_surface",
            route: `/features?lon=${lon}&lat=${lat}&zoom=${zoom}&kind=${kind}&page_size=${size}`,
            surface: "features-map",
            uiAction: `map deep link ${placeName} kind=${kind} viewport=${viewport}`,
          });
        }
      }
    }
  }

  for (const featureId of featureIds) {
    for (const apiKind of ["admin", "weather", "price", "nearby"] as const) {
      for (const viewport of VIEWPORTS) {
        addScenario(scenarios, {
          apiExpectation:
            apiKind === "admin"
              ? "/v1/admin/features/{feature_id}"
              : apiKind === "weather"
                ? "/v1/admin/features/{feature_id}/weather"
                : apiKind === "price"
                  ? "/v1/admin/features/{feature_id}/price"
                : apiKind === "nearby"
                  ? "/v1/features/nearby"
                  : "/v1/admin/features/{feature_id}",
          idParts: ["feature-detail", featureId, apiKind, viewport],
          mode: "catalog",
          reflectedSurface: "/admin/features",
          risk: "cross_surface",
          route: `/features/${encodeURIComponent(featureId)}`,
          surface: "feature-detail",
          uiAction: `open feature detail ${featureId} and verify ${apiKind} panel at ${viewport}`,
        });
      }
    }
  }

  // T-VN-40C: legacy `curated_features` list/detail API와 상세 라우트가 사라져,
  // 이 축은 canonical collection/item 축(`/v1/admin/curations`)으로 옮겼다. 상세는
  // 별도 라우트가 아니라 collections 화면 안에서 열리므로 reflectedSurface도 같은
  // 화면이다.
  for (const curationItemId of curationItemIds) {
    for (const term of searchTerms) {
      for (const size of pageSizes) {
        addScenario(scenarios, {
          apiExpectation:
            "/v1/admin/curations list and /v1/admin/curations/{collection_id}/items detail parity",
          idParts: ["curation-item", curationItemId, term, String(size)],
          mode: "catalog",
          reflectedSurface: "/admin/features/curated",
          risk: "cross_surface",
          route: `/admin/features/curated?q=${encodeURIComponent(term)}&page_size=${size}`,
          surface: "curated-features",
          uiAction: `filter curation collections by ${term}, open item ${curationItemId}`,
        });
      }
    }
  }

  for (const tab of LOG_TABS) {
    for (const term of searchTerms) {
      for (const size of pageSizes) {
        for (const level of LOG_LEVELS) {
          addScenario(scenarios, {
            apiExpectation:
              tab === "api"
                ? "/v1/ops/api-call-logs"
                : "/v1/ops/system-logs",
            idParts: ["logs", tab, term, String(size), level],
            mode: "catalog",
            reflectedSurface: "/ops/pipeline",
            risk: "read",
            route: `/ops/logs?tab=${tab}&q=${encodeURIComponent(term)}&page_size=${size}&level=${level}`,
            surface: "logs",
            uiAction: `logs tab=${tab}, q=${term}, level=${level}, size=${size}`,
          });
        }
      }
    }
  }

  for (const reviewSurface of ["dedup-reviews", "enrichment-reviews"] as const) {
    for (const status of REVIEW_STATUSES) {
      for (const size of pageSizes) {
        for (const term of searchTerms) {
          addScenario(scenarios, {
            apiExpectation: `/v1/admin/${reviewSurface}`,
            idParts: [reviewSurface, status, String(size), term],
            mode: "catalog",
            reflectedSurface: "/admin/features",
            risk: "write",
            route: `/admin/${reviewSurface}?status=${status}&page_size=${size}&q=${encodeURIComponent(term)}`,
            surface: reviewSurface,
            uiAction: `review status=${status}, q=${term}, size=${size}; accept/reject must reflect in feature surfaces`,
          });
        }
      }
    }
  }

  // T-VN-36(0104) 이후 change-review surface가 없으므로 그 축의 catalog 시나리오도
  // 발행하지 않는다.

  for (const category of categories) {
    for (const size of pageSizes) {
      for (const viewport of VIEWPORTS) {
        addScenario(scenarios, {
          apiExpectation:
            "/v1/admin/features category-ish search and /v1/features map parity",
          idParts: ["category-cross", category, String(size), viewport],
          mode: "catalog",
          reflectedSurface: "/features",
          risk: "cross_surface",
          route: `/admin/features?q=${category}&page_size=${size}`,
          surface: "admin-features",
          uiAction: `category code ${category} search at ${viewport}`,
        });
      }
    }
  }

  return scenarios;
}

export function summarizeAdminLiveScenarioCatalog(
  scenarios: readonly AdminLiveScenario[],
) {
  const byRisk = Object.fromEntries(
    (["read", "write", "destructive", "cross_surface"] as const).map((risk) => [
      risk,
      scenarios.filter((scenario) => scenario.risk === risk).length,
    ]),
  ) as Record<AdminLiveScenarioRisk, number>;
  const bySurface = Object.fromEntries(
    ADMIN_SURFACES.map((surface) => [
      surface.id,
      scenarios.filter((scenario) => scenario.surface === surface.id).length,
    ]),
  );
  return {
    byRisk,
    bySurface,
    total: scenarios.length,
  };
}
