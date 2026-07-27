import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const expectedNextVersion = "16.2.12";
const expectedSharpVersion = "0.35.3";

function installedVersion(packageName) {
  const packageJsonPath = require.resolve(`${packageName}/package.json`);
  return JSON.parse(readFileSync(packageJsonPath, "utf8")).version;
}

assert.equal(
  installedVersion("next"),
  expectedNextVersion,
  "검증되지 않은 Next 버전입니다.",
);
assert.equal(
  require("sharp").versions.sharp,
  expectedSharpVersion,
  "검증되지 않은 Sharp ABI 버전입니다.",
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

console.log("Next 16.2.12 / Sharp 0.35.3 optimizer ABI smoke 통과");
