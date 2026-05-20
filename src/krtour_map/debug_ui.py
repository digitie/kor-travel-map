from __future__ import annotations

# ruff: noqa: E501
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from krtour_map.debug_api import handle

DEFAULT_DEBUG_UI_HOST = "127.0.0.1"
DEFAULT_DEBUG_API_HOST = "127.0.0.1"
DEFAULT_DEBUG_UI_PORT = 8600
DEFAULT_DEBUG_API_PORT = 8601
DEFAULT_DEBUG_API_URL = "http://localhost:8601/api/debug"
KAKAO_JS_API_KEY = "b93b82c48729c08c24c943911a8727f9"


def render_debug_ui_html(api_url: str = DEFAULT_DEBUG_API_URL) -> str:
    """Return the local-only React debug UI HTML."""

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>python-krtour-map Debug UI</title>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={KAKAO_JS_API_KEY}&autoload=false"></script>
  <script type="importmap">
    {{
      "imports": {{
        "react": "https://esm.sh/react@18.2.0",
        "react-dom/client": "https://esm.sh/react-dom@18.2.0/client"
      }}
    }}
  </script>
  <style>
    :root {{
      color-scheme: light;
      font-family: "Noto Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f7f8;
      color: #17202a;
    }}
    body {{ margin: 0; min-width: 320px; }}
    header {{
      height: 56px; display: flex; align-items: center; gap: 16px; padding: 0 18px;
      background: #13212c; color: #f8fafc; border-bottom: 3px solid #2f9e8f;
    }}
    header strong {{ font-size: 16px; }}
    header span {{ color: #b7c7d1; font-size: 13px; }}
    main {{
      display: grid; grid-template-columns: minmax(360px, 430px) minmax(0, 1fr);
      gap: 14px; padding: 14px; height: calc(100vh - 84px); box-sizing: border-box;
    }}
    aside, .workbench {{
      min-height: 0; overflow: auto; background: #ffffff; border: 1px solid #d7dee3;
      border-radius: 8px;
    }}
    aside {{ padding: 12px; }}
    .workbench {{ display: grid; grid-template-rows: minmax(300px, 1fr) minmax(180px, 35%); }}
    .toolbar {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .triple {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }}
    label {{ display: block; margin-top: 10px; font-size: 12px; font-weight: 700; color: #384854; }}
    input, select, textarea, button {{
      box-sizing: border-box; width: 100%; min-height: 36px; border: 1px solid #bac6ce;
      border-radius: 6px; background: #ffffff; color: #17202a; font: inherit; font-size: 13px;
    }}
    input, select {{ padding: 7px 9px; }}
    textarea {{ min-height: 156px; padding: 9px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    button {{
      padding: 7px 10px; cursor: pointer; background: #225ea8; color: #ffffff; border-color: #225ea8;
      font-weight: 700;
    }}
    button.secondary {{ background: #536471; border-color: #536471; }}
    button.success {{ background: #1f7a5c; border-color: #1f7a5c; }}
    button:disabled {{ opacity: .55; cursor: default; }}
    .map {{ min-height: 300px; }}
    .map-shell {{ position: relative; min-height: 300px; }}
    .map-meta {{
      position: absolute; z-index: 2; top: 10px; left: 10px; display: flex; gap: 6px; flex-wrap: wrap;
      max-width: calc(100% - 20px);
    }}
    .pill {{
      display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; border-radius: 999px;
      background: rgba(255,255,255,.94); border: 1px solid #d7dee3; color: #384854; font-size: 12px;
      box-shadow: 0 6px 18px rgba(18,32,44,.12);
    }}
    .marker {{
      position: relative; transform: translate(-50%, -100%); min-width: 30px; height: 30px;
      width: auto; min-height: 30px; padding: 0 8px;
      display: inline-flex; align-items: center; justify-content: center; border-radius: 16px 16px 16px 4px;
      background: #225ea8; color: #fff; border: 2px solid #fff; box-shadow: 0 8px 18px rgba(18,32,44,.28);
      font-weight: 900; font-size: 12px; cursor: pointer;
    }}
    .marker.notice {{ border-radius: 8px 8px 8px 2px; }}
    .marker.route {{ border-radius: 999px; }}
    .marker .marker-tip {{
      position: absolute; left: 50%; bottom: -26px; transform: translateX(-50%);
      min-width: 92px; max-width: 190px; padding: 4px 7px; border-radius: 6px;
      background: rgba(23,32,42,.92); color: #fff; font-size: 11px; font-weight: 700;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; opacity: 0; pointer-events: none;
    }}
    .marker:hover .marker-tip {{ opacity: 1; }}
    .split {{ display: grid; grid-template-columns: minmax(240px, 36%) minmax(0, 1fr); min-height: 0; border-top: 1px solid #d7dee3; }}
    .list {{ overflow: auto; border-right: 1px solid #d7dee3; }}
    .item {{
      width: 100%; border: 0; border-bottom: 1px solid #e4eaee; border-radius: 0; background: #ffffff;
      color: #17202a; text-align: left; padding: 10px 12px; display: grid; gap: 2px;
    }}
    .item.active {{ background: #eaf6f3; }}
    .item b {{ font-size: 13px; }}
    .item span {{ font-size: 12px; color: #61717d; }}
    .item small {{ color: #225ea8; font-weight: 800; font-size: 11px; }}
    .detail {{
      min-height: 0; overflow: auto; background: #fbfcfd; display: grid; grid-template-rows: auto minmax(0,1fr);
    }}
    .detail-card {{ padding: 12px; border-bottom: 1px solid #e4eaee; background: #ffffff; }}
    .detail-card h2 {{ margin: 0 0 6px; font-size: 15px; line-height: 1.25; }}
    .detail-card .meta {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
    .detail-card code {{ background: #edf2f7; padding: 2px 5px; border-radius: 4px; font-size: 11px; }}
    .filters {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    pre {{
      margin: 0; padding: 12px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
      font-size: 12px; line-height: 1.45; background: #fbfcfd; min-height: 100%;
    }}
    .rustfs-link {{ display: block; margin-top: 8px; color: #225ea8; font-size: 13px; }}
    @media (max-width: 940px) {{
      main {{ grid-template-columns: 1fr; height: auto; }}
      .workbench {{ min-height: 720px; }}
      .split {{ grid-template-columns: 1fr; }}
      .list {{ border-right: 0; border-bottom: 1px solid #d7dee3; max-height: 220px; }}
    }}
  </style>
</head>
<body>
  <header>
    <strong>python-krtour-map Debug UI</strong>
    <span>frontend 8600 · backend 8601 · Kakao domain http://localhost:8600</span>
  </header>
  <div id="root"></div>
  <script type="module">
    import React, {{useEffect, useMemo, useState}} from "react";
    import {{createRoot}} from "react-dom/client";
    import {{CustomOverlayMap, Map}} from "https://esm.sh/react-kakao-maps-sdk@1.1.27?deps=react@18.2.0,react-dom@18.2.0";

    const h = React.createElement;
    const API_URL = {json.dumps(api_url)};
    const SAMPLE_ROUTE = [
      {{
        "stretNm": "남산 무장애산책길",
        "stretIntrcn": "휠체어 이용 가능한 무장애 산책로",
        "stretLt": "800m",
        "reqreTime": "40분",
        "beginSpotNm": "입구",
        "beginRdnmadr": "서울특별시 중구",
        "endSpotNm": "전망대",
        "endRdnmadr": "서울특별시 중구",
        "referenceDate": "2026-02-09",
        "instt_code": "6110000"
      }}
    ];
    const SAMPLE_NOTICE = [
      {{
        "notice_id": "debug-krex-traffic-1",
        "title": "영동선 강릉방향 사고 처리",
        "message": "영동선 강릉방향 123K 부근 1차로 사고 처리 중",
        "lat": 37.543,
        "lon": 128.442,
        "source_agency": "한국도로공사",
        "valid_start_time": "2026-05-20T09:00:00+09:00",
        "severity": 4
      }},
      {{
        "notice_id": "debug-kma-rain-1",
        "title": "서울 호우주의보",
        "message": "서울 전역 호우주의보 발효",
        "lat": 37.5665,
        "lon": 126.978,
        "source_agency": "기상청",
        "valid_start_time": "2026-05-20T10:00:00+09:00"
      }}
    ];

    function App() {{
      const [databaseUrl, setDatabaseUrl] = useState("sqlite+pysqlite:///./artifacts/debug-ui.sqlite3");
      const [datasetKey, setDatasetKey] = useState("standard_tourism_roads");
      const [rawItems, setRawItems] = useState(JSON.stringify(SAMPLE_ROUTE, null, 2));
      const [query, setQuery] = useState("");
      const [kindFilter, setKindFilter] = useState("");
      const [noticeTypeFilter, setNoticeTypeFilter] = useState("");
      const [onlyViewport, setOnlyViewport] = useState(true);
      const [bounds, setBounds] = useState(null);
      const [features, setFeatures] = useState([]);
      const [selected, setSelected] = useState(null);
      const [output, setOutput] = useState({{ready: true, api_url: API_URL}});
      const [busy, setBusy] = useState(false);
      const [rustfs, setRustfs] = useState(null);

      useEffect(() => {{
        run("defaults").then((result) => {{
          setOutput(result);
          setRustfs(result.rustfs || null);
        }});
        listFeatures();
      }}, []);

      useEffect(() => {{
        if (datasetKey.startsWith("krex_") || datasetKey.startsWith("kma_") || datasetKey.startsWith("forest_safety") || datasetKey.startsWith("khoa_coastal")) {{
          setRawItems(JSON.stringify(SAMPLE_NOTICE, null, 2));
        }} else if (datasetKey === "standard_tourism_roads") {{
          setRawItems(JSON.stringify(SAMPLE_ROUTE, null, 2));
        }}
      }}, [datasetKey]);

      async function api(payload) {{
        setBusy(true);
        try {{
          const response = await fetch(API_URL, {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify(payload)
          }});
          const result = await response.json();
          setOutput(result);
          return result;
        }} catch (error) {{
          const result = {{ok: false, error: String(error)}};
          setOutput(result);
          return result;
        }} finally {{
          setBusy(false);
        }}
      }}

      function parsedItems() {{
        const value = rawItems.trim();
        return value ? JSON.parse(value) : [];
      }}

      async function run(action, extra = {{}}) {{
        return await api({{action, database_url: databaseUrl, ...extra}});
      }}

      function isNoticeDataset() {{
        return ["krex_traffic_notices", "kma_weather_alerts", "forest_safety_notices", "khoa_coastal_notices"].includes(datasetKey);
      }}

      async function listFeatures() {{
        const filters = {{only_with_coord: true}};
        if (kindFilter) filters.kind = kindFilter;
        if (noticeTypeFilter) filters.notice_type = noticeTypeFilter;
        const result = await run("list_features", {{
          q: query,
          limit: 500,
          filters,
          bounds: onlyViewport ? bounds : null
        }});
        if (result.ok) setFeatures(result.items || []);
      }}

      async function getFeature(feature) {{
        setSelected(feature);
        await run("get_feature", {{feature_id: feature.feature_id}});
      }}

      async function previewStandard() {{
        await run(isNoticeDataset() ? "preview_notice_data" : "preview_standard_data", {{dataset_key: datasetKey, items: parsedItems()}});
      }}

      async function loadStandard() {{
        await run(isNoticeDataset() ? "load_notice_data" : "load_standard_data", {{dataset_key: datasetKey, items: parsedItems()}});
        await listFeatures();
      }}

      async function runDagster() {{
        await run("run_dagster_etl", {{dataset_key: datasetKey, items: parsedItems(), run_type: "manual"}});
        await listFeatures();
      }}

      async function refreshRustfs() {{
        const result = await api({{action: "rustfs_config"}});
        if (result.ok) setRustfs({{config_path: result.config_path, settings: result.settings, console_url: result.console_url}});
      }}

      async function saveRustfs() {{
        const form = document.getElementById("rustfsForm");
        const config = Object.fromEntries(new FormData(form).entries());
        config.enabled = form.elements.enabled.checked;
        config.upload_url_expires_seconds = Number(config.upload_url_expires_seconds || 900);
        config.max_upload_bytes = Number(config.max_upload_bytes || 10485760);
        config.allowed_content_types = String(config.allowed_content_types || "").split(",").map((item) => item.trim()).filter(Boolean);
        const result = await api({{action: "save_rustfs_config", config}});
        if (result.ok) setRustfs({{config_path: result.config_path, settings: result.settings, console_url: result.console_url}});
      }}

      async function listRustfsFiles() {{
        await api({{action: "rustfs_files", prefix: document.getElementById("rustfsPrefix").value, max_keys: 100}});
      }}

      const markers = features.filter((feature) => feature.coord && feature.coord.latitude && feature.coord.longitude);
      const center = useMemo(() => {{
        const first = markers[0];
        return first ? {{lat: first.coord.latitude, lng: first.coord.longitude}} : {{lat: 37.5665, lng: 126.9780}};
      }}, [features]);

      function updateBounds(map) {{
        const next = map.getBounds();
        const sw = next.getSouthWest();
        const ne = next.getNorthEast();
        setBounds({{south: sw.getLat(), west: sw.getLng(), north: ne.getLat(), east: ne.getLng()}});
      }}

      function markerGlyph(feature) {{
        const icon = feature.notice_type || feature.route_type || feature.marker_icon || feature.category_maki_icon || "";
        if (feature.kind === "notice") {{
          if (icon.includes("accident")) return "!";
          if (icon.includes("rain")) return "R";
          if (icon.includes("snow")) return "S";
          if (icon.includes("heat")) return "H";
          if (icon.includes("landslide")) return "L";
          if (icon.includes("earthquake")) return "E";
          return "!";
        }}
        if (feature.kind === "route") return "R";
        if (feature.kind === "event") return "E";
        if (feature.kind === "area") return "A";
        return (feature.marker_icon || "P").slice(0, 1).toUpperCase();
      }}

      function detailSummary(feature) {{
        if (!feature) return null;
        const chips = [
          feature.kind,
          feature.notice_type || feature.route_type || feature.category_label || feature.category,
          feature.legal_dong_code,
          feature.notice_severity ? `severity ${{feature.notice_severity}}` : null
        ].filter(Boolean);
        return h("div", {{className: "detail-card"}},
          h("h2", null, feature.name),
          h("div", null, feature.coord ? `${{feature.coord.latitude.toFixed(6)}}, ${{feature.coord.longitude.toFixed(6)}}` : "no coordinate"),
          h("div", {{className: "meta"}}, chips.map((chip) => h("code", {{key: chip}}, chip))),
          feature.valid_start_time ? h("div", {{className: "meta"}}, h("span", {{className: "pill"}}, `valid ${{feature.valid_start_time}}`)) : null
        );
      }}

      return h("main", null,
        h("aside", null,
          h("label", null, "Database URL"),
          h("input", {{value: databaseUrl, onChange: (event) => setDatabaseUrl(event.target.value)}}),
          h("div", {{className: "toolbar"}},
            h("button", {{disabled: busy, onClick: () => run("schema", {{create_schema: true}})}}, "Schema"),
            h("button", {{disabled: busy, className: "secondary", onClick: () => run("dagster_jobs")}}, "Dagster")
          ),
          h("label", null, "Standard Dataset"),
          h("select", {{value: datasetKey, onChange: (event) => setDatasetKey(event.target.value)}},
            h("option", {{value: "standard_tourism_roads"}}, "전국길관광정보표준데이터 route"),
            h("option", {{value: "standard_museums"}}, "전국박물관미술관정보표준데이터 place"),
            h("option", {{value: "standard_parking_lots"}}, "전국주차장정보표준데이터 place"),
            h("option", {{value: "standard_tourist_sites"}}, "전국관광지정보표준데이터 place"),
            h("option", {{value: "standard_cultural_festivals"}}, "전국문화축제표준데이터 event"),
            h("option", {{value: "krex_traffic_notices"}}, "도로공사 사고/공사 notice"),
            h("option", {{value: "kma_weather_alerts"}}, "기상청 특보 notice"),
            h("option", {{value: "forest_safety_notices"}}, "산림 안전 notice"),
            h("option", {{value: "khoa_coastal_notices"}}, "해양 갈라짐 notice")
          ),
          h("label", null, "Raw Items JSON"),
          h("textarea", {{value: rawItems, onChange: (event) => setRawItems(event.target.value)}}),
          h("div", {{className: "triple"}},
            h("button", {{disabled: busy, onClick: previewStandard}}, "Preview"),
            h("button", {{disabled: busy, className: "secondary", onClick: loadStandard}}, "Load"),
            h("button", {{disabled: busy, className: "success", onClick: runDagster}}, "Dagster Run")
          ),
          h("label", null, "Feature Search"),
          h("input", {{value: query, onChange: (event) => setQuery(event.target.value), placeholder: "name, id, category"}}),
          h("div", {{className: "filters"}},
            h("select", {{value: kindFilter, onChange: (event) => setKindFilter(event.target.value)}},
              h("option", {{value: ""}}, "all feature kinds"),
              h("option", {{value: "place"}}, "place"),
              h("option", {{value: "route"}}, "route"),
              h("option", {{value: "area"}}, "area"),
              h("option", {{value: "event"}}, "event"),
              h("option", {{value: "notice"}}, "notice"),
              h("option", {{value: "weather"}}, "weather"),
              h("option", {{value: "price"}}, "price")
            ),
            h("select", {{value: noticeTypeFilter, onChange: (event) => setNoticeTypeFilter(event.target.value)}},
              h("option", {{value: ""}}, "all notice types"),
              h("option", {{value: "traffic_accident"}}, "traffic accident"),
              h("option", {{value: "roadwork"}}, "roadwork"),
              h("option", {{value: "road_closure"}}, "road closure"),
              h("option", {{value: "heavy_rain_warning"}}, "heavy rain"),
              h("option", {{value: "heavy_snow_warning"}}, "heavy snow"),
              h("option", {{value: "heat_wave_warning"}}, "heat wave"),
              h("option", {{value: "earthquake"}}, "earthquake"),
              h("option", {{value: "landslide_warning"}}, "landslide"),
              h("option", {{value: "coastal_isolation"}}, "coastal")
            )
          ),
          h("label", null, h("input", {{type: "checkbox", checked: onlyViewport, onChange: (event) => setOnlyViewport(event.target.checked), style: {{width: 16, minHeight: 16, marginRight: 8}}}}), "Only visible map bounds"),
          h("button", {{disabled: busy, onClick: listFeatures}}, "List Features"),
          h("form", {{id: "rustfsForm", key: rustfs?.config_path || "rustfsForm"}},
            h("label", null, "RustFS Endpoint"),
            h("input", {{name: "endpoint_url", defaultValue: rustfs?.settings?.endpoint_url || "http://127.0.0.1:19000"}}),
            h("label", null, "RustFS Console"),
            h("input", {{name: "console_url", defaultValue: rustfs?.settings?.console_url || "http://127.0.0.1:19001"}}),
            h("label", null, "Bucket"),
            h("input", {{name: "bucket", defaultValue: rustfs?.settings?.bucket || "tripmate-media"}}),
            h("label", null, "Access Key"),
            h("input", {{name: "access_key_id", defaultValue: rustfs?.settings?.access_key_id || ""}}),
            h("label", null, "Secret Key"),
            h("input", {{name: "secret_access_key", type: "password", defaultValue: rustfs?.settings?.secret_access_key || ""}}),
            h("label", null, "Allowed Content Types"),
            h("input", {{name: "allowed_content_types", defaultValue: (rustfs?.settings?.allowed_content_types || []).join(",")}}),
            h("input", {{name: "region", type: "hidden", defaultValue: rustfs?.settings?.region || "us-east-1"}}),
            h("input", {{name: "public_endpoint_url", type: "hidden", defaultValue: rustfs?.settings?.public_endpoint_url || "http://127.0.0.1:19000"}}),
            h("input", {{name: "public_base_url", type: "hidden", defaultValue: rustfs?.settings?.public_base_url || ""}}),
            h("input", {{name: "upload_url_expires_seconds", type: "hidden", defaultValue: rustfs?.settings?.upload_url_expires_seconds || 900}}),
            h("input", {{name: "max_upload_bytes", type: "hidden", defaultValue: rustfs?.settings?.max_upload_bytes || 10485760}}),
            h("label", null, h("input", {{name: "enabled", type: "checkbox", defaultChecked: rustfs?.settings?.enabled !== false, style: {{width: 16, minHeight: 16, marginRight: 8}}}}), "Enabled")
          ),
          h("div", {{className: "triple"}},
            h("button", {{disabled: busy, className: "secondary", onClick: refreshRustfs}}, "Read RustFS"),
            h("button", {{disabled: busy, className: "secondary", onClick: saveRustfs}}, "Save RustFS"),
            h("button", {{disabled: busy, className: "secondary", onClick: listRustfsFiles}}, "List Files")
          ),
          h("input", {{id: "rustfsPrefix", placeholder: "feature-files/", style: {{marginTop: 8}}}}),
          rustfs?.console_url ? h("a", {{className: "rustfs-link", href: rustfs.console_url, target: "_blank", rel: "noreferrer"}}, "RustFS UI") : null
        ),
        h("section", {{className: "workbench"}},
          h("div", {{className: "map map-shell"}},
            h("div", {{className: "map-meta"}},
              h("span", {{className: "pill"}}, `${{features.length}} rows`),
              h("span", {{className: "pill"}}, `${{markers.length}} markers`),
              onlyViewport ? h("span", {{className: "pill"}}, "viewport query") : null
            ),
            h(Map, {{
              center,
              style: {{width: "100%", height: "100%"}},
              level: 8,
              onIdle: (map) => updateBounds(map)
            }},
              markers.map((feature) => h(CustomOverlayMap, {{
                key: feature.feature_id,
                position: {{lat: feature.coord.latitude, lng: feature.coord.longitude}},
                yAnchor: 1
              }},
                h("button", {{
                  className: "marker " + feature.kind,
                  title: `${{feature.marker_icon || feature.category_maki_icon || "marker"}} · ${{feature.name}}`,
                  style: {{background: feature.marker_color || "#225ea8"}},
                  onClick: () => getFeature(feature)
                }},
                  markerGlyph(feature),
                  h("span", {{className: "marker-tip"}}, feature.notice_type || feature.route_type || feature.name)
                )
              ))
            )
          ),
          h("div", {{className: "split"}},
            h("div", {{className: "list"}},
              features.map((feature) => h("button", {{
                key: feature.feature_id,
                className: "item" + (selected?.feature_id === feature.feature_id ? " active" : ""),
                onClick: () => getFeature(feature)
              }},
                h("b", null, feature.name),
                feature.notice_type ? h("small", null, `${{feature.notice_type}} · ${{feature.marker_icon || "maki"}}`) : null,
                feature.route_type ? h("small", null, `${{feature.route_type}}`) : null,
                h("span", null, `${{feature.kind}} · ${{feature.category_label || feature.category}}`),
                h("span", null, feature.feature_id)
              ))
            ),
            h("div", {{className: "detail"}},
              detailSummary(selected),
              h("pre", null, JSON.stringify(output, null, 2))
            )
          )
        )
      );
    }}

    kakao.maps.load(() => createRoot(document.getElementById("root")).render(h(App)));
  </script>
</body>
</html>"""


def serve_debug_ui(
    *,
    host: str = DEFAULT_DEBUG_UI_HOST,
    port: int = DEFAULT_DEBUG_UI_PORT,
    api_host: str = DEFAULT_DEBUG_API_HOST,
    api_port: int = DEFAULT_DEBUG_API_PORT,
) -> None:
    """Serve the local React frontend and JSON backend until interrupted."""

    api_server = ThreadingHTTPServer((api_host, api_port), _DebugApiHandler)
    frontend_server = ThreadingHTTPServer((host, port), _DebugFrontendHandler)
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()
    try:
        print(f"Debug UI: http://localhost:{port}")
        print(f"Debug API: http://localhost:{api_port}/api/debug")
        frontend_server.serve_forever()
    finally:
        frontend_server.server_close()
        api_server.shutdown()
        api_server.server_close()
        api_thread.join(timeout=2)


class _DebugFrontendHandler(BaseHTTPRequestHandler):
    server_version = "KrtourMapDebugFrontend/0.2"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        if self.path not in {"/", "/index.html"}:
            self.send_error(404)
            return
        self._send(200, render_debug_ui_html(), "text/html; charset=utf-8")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: str, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _DebugApiHandler(BaseHTTPRequestHandler):
    server_version = "KrtourMapDebugAPI/0.2"

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._send(204, "", "application/json")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        if self.path != "/api/debug":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("request payload must be a JSON object")
            result: dict[str, Any] = handle(payload)
            self._send(200, json.dumps(result, ensure_ascii=False), "application/json")
        except Exception as exc:  # noqa: BLE001 - return the error to the local UI.
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
            self._send(500, body, "application/json")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: str, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8600")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if encoded:
            self.wfile.write(encoded)


def main() -> None:
    serve_debug_ui()


if __name__ == "__main__":
    main()
