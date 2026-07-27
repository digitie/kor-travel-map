import { existsSync, readFileSync, writeFileSync } from "node:fs";

const packageRoot = "node_modules/@redocly/openapi-core";
const packageJsonPath = `${packageRoot}/package.json`;
if (!existsSync(packageJsonPath)) {
  console.log(
    "@redocly/openapi-core 미설치(dev 의존성 생략) — vendor patch 생략",
  );
  process.exit(0);
}

const installed = JSON.parse(
  readFileSync(packageJsonPath, "utf8"),
);
const expectedVersion = "1.34.17";

if (installed.version !== expectedVersion) {
  throw new Error(
    `@redocly/openapi-core ${installed.version}은 검증된 ${expectedVersion}과 다릅니다. ` +
      "override·vendor patch를 재검토하세요.",
  );
}

const targets = [
  {
    path: `${packageRoot}/lib/utils.js`,
    before: "    return minimatch(url, pattern);",
    after: "    return minimatch.minimatch(url, pattern);",
  },
  {
    path: `${packageRoot}/src/utils.ts`,
    before: "  return minimatch(url, pattern);",
    after: "  return minimatch.minimatch(url, pattern);",
  },
];

for (const target of targets) {
  const source = readFileSync(target.path, "utf8");
  const beforeCount = source.split(target.before).length - 1;
  const afterCount = source.split(target.after).length - 1;

  if (beforeCount === 0 && afterCount === 1) {
    continue;
  }
  if (beforeCount !== 1 || afterCount !== 0) {
    throw new Error(
      `${target.path}의 minimatch API 경계가 예상과 다릅니다 ` +
        `(before=${beforeCount}, after=${afterCount}).`,
    );
  }
  writeFileSync(target.path, source.replace(target.before, target.after));
}

console.log(`@redocly/openapi-core@${expectedVersion} vendor patch 적용 완료`);
