/**
 * maplibre-gl worker를 `public/maplibre/`로 복사한다.
 *
 * **왜 필요한가.** Next 16의 production 빌드는 Turbopack이고, Turbopack은 URL
 * import를 해시된 단일 asset으로 처리하면서 **형제 파일을 함께 내보내지 않는다.**
 * maplibre 6은 worker를 `new Worker(blobUrl, {type: "module"})`로 띄우는데 그
 * worker(`maplibre-gl-worker.mjs`)는 `maplibre-gl-shared.mjs`를 **상대 경로로
 * import** 한다. blob URL에서는 그 상대 import를 풀 수 없어 worker가 **조용히**
 * 죽는다 — 생성자는 성공하고, 에러 이벤트도 나지 않으며, 그저 아무 메시지도
 * 돌려주지 않는다.
 *
 * prod 실측(2026-09-18 n150): 그 상태에서 GeoJSON source가 하나도 tile을 만들지
 * 못한다. `isSourceLoaded()`가 영원히 false라 `isStyleLoaded()`도 false가 되고,
 * `querySourceFeatures()`가 0을 돌려줘 **zoom 14 이상에서 마커가 한 개도 그려지지
 * 않았다.** raster(VWorld)는 worker를 쓰지 않아 멀쩡했기 때문에 "지도는 나오는데
 * feature만 사라진다"로 보였다.
 *
 * 처방은 상류 문서의 Turbopack 절 그대로다 — worker와 shared를 **같은 디렉터리**에
 * 복사해 정적으로 서빙하고 `setWorkerUrl`로 그 경로를 가리킨다. 둘을 함께 옮기지
 * 않으면 상대 import가 다시 깨진다.
 *
 * `predev`/`prebuild`에서 돈다.
 */

import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const WORKER_FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

const require = createRequire(import.meta.url);
const dist = path.join(
  path.dirname(require.resolve("maplibre-gl/package.json")),
  "dist",
);
const dest = path.join(process.cwd(), "public", "maplibre");

mkdirSync(dest, { recursive: true });
for (const file of WORKER_FILES) {
  copyFileSync(path.join(dist, file), path.join(dest, file));
}

console.log(`maplibre worker 복사: ${WORKER_FILES.join(", ")} -> ${dest}`);
