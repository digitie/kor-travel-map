import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

const expectedNpmVersion = "10.9.4";
const expectedProblems = [
  "extraneous: @emnapi/core@1.11.2",
  "extraneous: @emnapi/runtime@1.11.2",
  "extraneous: @emnapi/wasi-threads@1.2.2",
  "extraneous: @img/sharp-wasm32@0.35.3",
  "extraneous: @napi-rs/wasm-runtime@1.1.6",
  "extraneous: @tybys/wasm-util@0.10.3",
];

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
const pathPrefix = ` ${process.cwd()}/node_modules/`;
const actualProblems = (tree.problems ?? [])
  .map((problem) => {
    const prefixIndex = problem.indexOf(pathPrefix);
    return prefixIndex === -1 ? problem : problem.slice(0, prefixIndex);
  })
  .sort();

assert.deepEqual(
  actualProblems,
  expectedProblems,
  "npm dependency tree 문제가 exact Sharp WASM optional 허용 목록과 다릅니다.",
);

console.log(
  "npm tree integrity 통과: Sharp WASM optional extraneous 6개만 exact 허용",
);
