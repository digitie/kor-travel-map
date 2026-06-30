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
const FEATURE_STATUSES = [
  "all",
  "active",
  "inactive",
  "hidden",
  "broken",
  "deleted",
] as const;
const LOG_TABS = ["system", "api", "job"] as const;
const LOG_LEVELS = ["all", "info", "warning", "error"] as const;
const REVIEW_STATUSES = [
  "all",
  "pending",
  "accepted",
  "rejected",
  "merged",
] as const;
const CHANGE_ACTIONS = ["add", "update", "delete"] as const;

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
      "/v1/ops/import-jobs",
      "/v1/admin/dedup-reviews",
      "/v1/ops/dagster/summary",
    ],
    writeApis: [],
    reflectedSurfaces: ["/ops/import-jobs", "/ops/providers", "/admin/dagster"],
  },
  {
    id: "features-map",
    route: "/features",
    readyHeading: "Feature 지도",
    readApis: ["/v1/features", "/v1/features/{feature_id}"],
    writeApis: [],
    reflectedSurfaces: ["/admin/features", "/features/{feature_id}"],
  },
  {
    id: "feature-detail",
    route: "/features/{feature_id}",
    readyHeading: "Feature 상세",
    readApis: [
      "/v1/features/{feature_id}",
      "/v1/admin/features/{feature_id}",
      "/v1/features/{feature_id}/weather",
      "/v1/features/nearby",
    ],
    writeApis: [],
    reflectedSurfaces: ["/features", "/admin/features"],
  },
  {
    id: "admin-features",
    route: "/admin/features",
    readyHeading: "Feature 목록",
    readApis: [
      "/v1/admin/features",
      "/v1/admin/features/{feature_id}",
      "/v1/features/{feature_id}",
    ],
    writeApis: [
      writeApi("POST", "/v1/admin/features/{feature_id}/deactivate"),
      writeApi("PATCH", "/v1/admin/features/{feature_id}"),
      writeApi("DELETE", "/v1/admin/features/{feature_id}", "destructive"),
    ],
    reflectedSurfaces: ["/features", "/features/{feature_id}"],
  },
  {
    id: "feature-change-requests",
    route: "/admin/features/change-requests",
    readyHeading: "Feature 변경",
    readApis: [],
    writeApis: [
      writeApi("POST", "/v1/admin/features/change-requests"),
      writeApi("POST", "/v1/admin/features"),
    ],
    reflectedSurfaces: [
      "/admin/features/change-reviews",
      "/admin/features",
      "/features/{feature_id}",
    ],
  },
  {
    id: "feature-change-reviews",
    route: "/admin/features/change-reviews",
    readyHeading: "Feature 검수",
    readApis: ["/v1/admin/features/change-requests"],
    writeApis: [
      writeApi(
        "POST",
        "/v1/admin/features/change-requests/{request_id}/approve",
      ),
      writeApi(
        "POST",
        "/v1/admin/features/change-requests/{request_id}/reject",
      ),
    ],
    reflectedSurfaces: ["/admin/features", "/features/{feature_id}"],
  },
  {
    id: "new-feature",
    route: "/admin/features/new",
    readyHeading: "New feature",
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
    route: "/admin/curated-features",
    readyHeading: "Curated features",
    readApis: [
      "/v1/admin/curated-features",
      "/v1/admin/curated-source-rules",
      "/v1/admin/curated-sources",
      "/v1/admin/curated-themes",
    ],
    writeApis: [
      writeApi("POST", "/v1/admin/curated-features"),
      writeApi("PATCH", "/v1/admin/curated-features/{curated_feature_id}"),
      writeApi(
        "DELETE",
        "/v1/admin/curated-features/{curated_feature_id}",
        "destructive",
      ),
      writeApi("PATCH", "/v1/admin/curated-source-rules/{rule_id}"),
      writeApi("POST", "/v1/curated-features/{curated_feature_id}/pinvi-copy"),
    ],
    reflectedSurfaces: ["/admin/curated-features/{curated_feature_id}"],
  },
  {
    id: "curated-feature-detail",
    route: "/admin/curated-features/{curated_feature_id}",
    readyHeading: "Curated feature detail",
    readApis: ["/v1/admin/curated-features/{curated_feature_id}"],
    writeApis: [
      writeApi("PATCH", "/v1/admin/curated-features/{curated_feature_id}"),
      writeApi(
        "DELETE",
        "/v1/admin/curated-features/{curated_feature_id}",
        "destructive",
      ),
    ],
    reflectedSurfaces: ["/admin/curated-features"],
  },
  {
    id: "issues",
    route: "/admin/issues",
    readyHeading: "Issues",
    readApis: ["/v1/admin/issues", "/v1/admin/issues/{issue_id}"],
    writeApis: [writeApi("PATCH", "/v1/admin/issues/{issue_id}")],
    reflectedSurfaces: ["/features/{feature_id}", "/ops/consistency"],
  },
  {
    id: "import-jobs",
    route: "/ops/import-jobs",
    readyHeading: "Import jobs",
    readApis: ["/v1/ops/import-jobs", "/v1/ops/live"],
    writeApis: [],
    reflectedSurfaces: ["/ops/logs", "/admin/dagster"],
  },
  {
    id: "import-job-detail",
    route: "/ops/import-jobs/{job_id}",
    readyHeading: "Import job",
    readApis: [
      "/v1/ops/import-jobs/{job_id}",
      "/v1/ops/import-jobs/{job_id}/events",
    ],
    writeApis: [writeApi("POST", "/v1/ops/import-jobs/{job_id}/cancel")],
    reflectedSurfaces: ["/ops/import-jobs", "/ops/logs"],
  },
  {
    id: "providers",
    route: "/ops/providers",
    readyHeading: "Providers",
    readApis: [
      "/v1/ops/providers",
      "/v1/ops/providers/{provider}",
      "/v1/admin/provider-refresh-policies",
    ],
    writeApis: [
      writeApi(
        "PUT",
        "/v1/admin/provider-refresh-policies/{provider}/{dataset_key}",
      ),
      writeApi("POST", "/v1/admin/feature-update-requests"),
    ],
    reflectedSurfaces: ["/admin/feature-update-requests", "/ops/logs"],
  },
  {
    id: "consistency",
    route: "/ops/consistency",
    readyHeading: "Consistency",
    readApis: [
      "/v1/ops/metrics",
      "/v1/ops/consistency/reports",
      "/v1/ops/consistency/issues",
    ],
    writeApis: [],
    reflectedSurfaces: ["/admin/issues"],
  },
  {
    id: "logs",
    route: "/ops/logs",
    readyHeading: "Logs",
    readApis: [
      "/v1/ops/system-logs",
      "/v1/ops/api-call-logs",
      "/v1/ops/import-job-events",
    ],
    writeApis: [],
    reflectedSurfaces: ["/ops/import-jobs", "/admin/settings"],
  },
  {
    id: "dedup-reviews",
    route: "/admin/dedup-reviews",
    readyHeading: "Dedup review",
    readApis: ["/v1/admin/dedup-reviews", "/v1/admin/dedup-reviews/{review_id}"],
    writeApis: [writeApi("PATCH", "/v1/admin/dedup-reviews/{review_id}")],
    reflectedSurfaces: ["/admin/features", "/features/{feature_id}"],
  },
  {
    id: "enrichment-reviews",
    route: "/admin/enrichment-reviews",
    readyHeading: "Enrichment review",
    readApis: [
      "/v1/admin/enrichment-reviews",
      "/v1/admin/enrichment-reviews/{review_id}",
    ],
    writeApis: [writeApi("PATCH", "/v1/admin/enrichment-reviews/{review_id}")],
    reflectedSurfaces: ["/admin/features", "/features/{feature_id}"],
  },
  {
    id: "feature-update-requests",
    route: "/admin/feature-update-requests",
    readyHeading: "Feature update requests",
    readApis: ["/v1/admin/feature-update-requests"],
    writeApis: [
      writeApi("POST", "/v1/admin/feature-update-requests"),
      writeApi(
        "POST",
        "/v1/admin/feature-update-requests/{request_id}/cancel",
      ),
      writeApi(
        "POST",
        "/v1/admin/feature-update-requests/{request_id}/run-now",
      ),
    ],
    reflectedSurfaces: ["/ops/import-jobs", "/ops/providers", "/features"],
  },
  {
    id: "feature-update-request-detail",
    route: "/admin/feature-update-requests/{request_id}",
    readyHeading: "Feature update request",
    readApis: ["/v1/admin/feature-update-requests/{request_id}"],
    writeApis: [
      writeApi(
        "POST",
        "/v1/admin/feature-update-requests/{request_id}/cancel",
      ),
      writeApi(
        "POST",
        "/v1/admin/feature-update-requests/{request_id}/run-now",
      ),
    ],
    reflectedSurfaces: ["/admin/feature-update-requests", "/ops/import-jobs"],
  },
  {
    id: "poi-cache-targets",
    route: "/admin/poi-cache-targets",
    readyHeading: "POI cache targets",
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
      writeApi("POST", "/v1/admin/feature-update-requests"),
    ],
    reflectedSurfaces: ["/features", "/admin/feature-update-requests"],
  },
  {
    id: "offline-uploads",
    route: "/admin/offline-uploads",
    readyHeading: "Offline uploads",
    readApis: [
      "/v1/admin/offline-uploads",
      "/v1/admin/offline-uploads/{upload_id}/preview",
      "/v1/admin/offline-uploads/{upload_id}/validation",
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
    reflectedSurfaces: ["/ops/import-jobs", "/ops/logs"],
  },
  {
    id: "backups",
    route: "/admin/backups",
    readyHeading: "Backups",
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
    id: "dagster",
    route: "/admin/dagster",
    readyHeading: "작업 자동화",
    readApis: [
      "/v1/ops/dagster/summary",
      "/v1/ops/dagster/runs/{run_id}",
    ],
    writeApis: [
      writeApi("POST", "/v1/ops/dagster/nux-seen"),
      writeApi("PATCH", "/v1/ops/dagster/schedules/{schedule_name}"),
      writeApi("POST", "/v1/ops/dagster/schedules/{schedule_name}/default"),
      writeApi("POST", "/v1/ops/dagster/schedules/{schedule_name}/run"),
      writeApi("POST", "/v1/ops/dagster/schedules/{schedule_name}/start"),
      writeApi("POST", "/v1/ops/dagster/schedules/{schedule_name}/stop"),
    ],
    reflectedSurfaces: ["/ops/import-jobs", "/ops/providers"],
  },
  {
    id: "settings",
    route: "/admin/settings",
    readyHeading: "Settings",
    readApis: ["/v1/admin/public-api-keys", "/v1/admin/auth-events"],
    writeApis: [
      writeApi("POST", "/v1/admin/public-api-keys"),
      writeApi("POST", "/v1/admin/public-api-keys/{public_api_key_id}/revoke"),
      writeApi("POST", "/v1/admin/auth-events"),
    ],
    reflectedSurfaces: ["/admin/settings", "/ops/logs"],
  },
  {
    id: "etl-preview",
    route: "/etl",
    readyHeading: "ETL preview",
    readApis: ["/v1/debug/etl/providers", "/v1/debug/etl/preview"],
    writeApis: [],
    reflectedSurfaces: ["/ops/providers", "/admin/features"],
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
  const curatedIds = F.CURATED_IDS.slice(0, 40);

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
      for (const status of FEATURE_STATUSES) {
        for (const size of pageSizes) {
          for (const order of ORDERS) {
            addScenario(scenarios, {
              apiExpectation:
                "/v1/admin/features q/kind/status/page_size/order query",
              idParts: [
                "admin-features",
                term,
                kind,
                status,
                String(size),
                order,
              ],
              mode: "catalog",
              reflectedSurface: "/features",
              risk: "cross_surface",
              route: "/admin/features",
              surface: "admin-features",
              uiAction: `search=${term}, kind=${kind}, status=${status}, size=${size}, order=${order}`,
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
              "/v1/features bbox query, then /v1/admin/features detail parity",
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
    for (const apiKind of ["public", "admin", "weather", "nearby"] as const) {
      for (const viewport of VIEWPORTS) {
        addScenario(scenarios, {
          apiExpectation:
            apiKind === "admin"
              ? "/v1/admin/features/{feature_id}"
              : apiKind === "weather"
                ? "/v1/features/{feature_id}/weather"
                : apiKind === "nearby"
                  ? "/v1/features/nearby"
                  : "/v1/features/{feature_id}",
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

  for (const curatedId of curatedIds) {
    for (const term of searchTerms) {
      for (const size of pageSizes) {
        addScenario(scenarios, {
          apiExpectation:
            "/v1/admin/curated-features list/detail and pinvi-copy preview parity",
          idParts: ["curated", curatedId, term, String(size)],
          mode: "catalog",
          reflectedSurface: `/admin/curated-features/${curatedId}`,
          risk: "cross_surface",
          route: `/admin/curated-features?q=${encodeURIComponent(term)}&page_size=${size}`,
          surface: "curated-features",
          uiAction: `filter curated candidates by ${term}, open ${curatedId}`,
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
                : tab === "job"
                  ? "/v1/ops/import-job-events"
                  : "/v1/ops/system-logs",
            idParts: ["logs", tab, term, String(size), level],
            mode: "catalog",
            reflectedSurface: "/ops/import-jobs",
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

  for (const action of CHANGE_ACTIONS) {
    for (const status of ["all", "pending", "applied", "rejected"] as const) {
      for (const term of searchTerms) {
        for (const size of pageSizes) {
          addScenario(scenarios, {
            apiExpectation:
              "/v1/admin/features/change-requests plus approve/reject endpoints",
            idParts: ["change-reviews", action, status, term, String(size)],
            mode: "catalog",
            reflectedSurface: "/admin/features",
            risk: "write",
            route: `/admin/features/change-reviews?action=${action}&status=${status}&q=${encodeURIComponent(term)}&page_size=${size}`,
            surface: "feature-change-reviews",
            uiAction: `action=${action}, status=${status}, q=${term}; approve/reject reflected in admin and public detail`,
          });
        }
      }
    }
  }

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
