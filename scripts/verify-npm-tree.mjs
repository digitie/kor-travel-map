import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

const expectedNpmVersion = "12.0.1";

const npmExecPath = process.env.npm_execpath;
assert.ok(
  npmExecPath,
  "verify:npm-tree는 exact npm run 경계에서 실행해야 합니다.",
);
const versionResult = spawnSync(process.execPath, [npmExecPath, "--version"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
if (versionResult.error) {
  throw versionResult.error;
}
assert.equal(versionResult.status, 0, "npm 실행기 버전 조회에 실패했습니다.");
assert.equal(
  versionResult.stdout.trim(),
  expectedNpmVersion,
  `npm ${expectedNpmVersion}이 아닌 실행기는 허용하지 않습니다.`,
);

const result = spawnSync(
  process.execPath,
  [npmExecPath, "ls", "--all", "--json"],
  {
    cwd: process.cwd(),
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
  },
);
if (result.error) {
  throw result.error;
}
assert.equal(
  result.status,
  0,
  `npm ls 실행 실패(status=${result.status ?? "signal"})`,
);

const tree = JSON.parse(result.stdout);
assert.deepEqual(
  tree.problems ?? [],
  [],
  "npm dependency tree에 허용되지 않은 문제가 있습니다.",
);

console.log("npm tree integrity 통과: problems 0개");
