// Next image optimizer가 이 트리의 sharp와 **실제로** 맞물리는지 본다.
//
// 왜: Next는 `sharp`를 native ABI로 부른다. 버전 짝이 어긋나면 `npm ci`도
// `next build`도 조용히 통과하고, 실패는 런타임 이미지 최적화 첫 요청에서만
// 난다. 그래서 여기서 한 장을 실제로 최적화해 본다.
//
// 기대 버전은 **매니페스트에서 읽는다.** 예전에는 이 파일이 `16.2.12` /
// `0.35.3`을 리터럴로 들고 있었는데, 그러면 보안 권고 하나에 세 자리를 고쳐야
// 하고(둘은 선언, 하나는 검사기) 그중 하나를 잊으면 이 검사가 "검증되지 않은
// 버전"이라며 무관한 얼굴로 죽는다 — 실제로 그렇게 죽었다. 검사가 지켜야 할
// 명제는 "선언한 핀과 설치된 트리가 같은가"이지 "버전이 특정 숫자인가"가 아니다.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function manifest(relativePath) {
  return JSON.parse(readFileSync(path.join(repoRoot, relativePath), "utf8"));
}

function exactPin(value, where) {
  assert.equal(
    typeof value,
    "string",
    `${where}에 핀이 없습니다 — 이 검사는 선언된 핀을 정본으로 씁니다.`,
  );
  assert.match(
    value,
    /^\d+\.\d+\.\d+$/u,
    `${where}는 정확한 버전이어야 합니다(범위 지정자 금지): ${value}`,
  );
  return value;
}

const expectedNextVersion = exactPin(
  manifest("packages/kor-travel-map-admin/frontend/package.json").dependencies
    ?.next,
  "frontend package.json dependencies.next",
);
const expectedSharpVersion = exactPin(
  manifest("package.json").overrides?.next?.sharp,
  "root package.json overrides.next.sharp",
);

function installedVersion(packageName) {
  const packageJsonPath = require.resolve(`${packageName}/package.json`);
  return JSON.parse(readFileSync(packageJsonPath, "utf8")).version;
}

assert.equal(
  installedVersion("next"),
  expectedNextVersion,
  "설치된 Next가 선언된 핀과 다릅니다.",
);
assert.equal(
  require("sharp").versions.sharp,
  expectedSharpVersion,
  "설치된 Sharp가 선언된 핀과 다릅니다.",
);

const { getImageSize, optimizeImage } = require(
  "next/dist/server/image-optimizer.js",
);
const source = Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">' +
    '<rect width="1" height="1" fill="#2f765f"/>' +
    "</svg>",
);
const optimized = await optimizeImage({
  buffer: source,
  contentType: "image/webp",
  quality: 80,
  width: 2,
  height: 2,
  limitInputPixels: 64,
  timeoutInSeconds: 5,
});

assert.equal(optimized.subarray(0, 4).toString("ascii"), "RIFF");
assert.equal(optimized.subarray(8, 12).toString("ascii"), "WEBP");
assert.deepEqual(await getImageSize(optimized), { width: 2, height: 2 });

console.log(
  `Next ${expectedNextVersion} / Sharp ${expectedSharpVersion} optimizer ABI smoke 통과`,
);
