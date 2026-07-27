import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const frontend = path.join(
  root,
  "packages",
  "kor-travel-map-admin",
  "frontend",
);
const eslint = new ESLint({ cwd: frontend });
const config = await eslint.calculateConfigForFile(
  path.join(frontend, "src", "app", "page.tsx"),
);

function severity(ruleName) {
  const configured = config.rules?.[ruleName];
  return Array.isArray(configured) ? configured[0] : configured;
}

assert.equal(severity("react-hooks/rules-of-hooks"), 2);
assert.equal(severity("react-hooks/exhaustive-deps"), 1);
for (const duplicateRule of [
  "error-boundaries",
  "exhaustive-deps",
  "purity",
  "rules-of-hooks",
  "set-state-in-effect",
  "set-state-in-render",
  "static-components",
  "unsupported-syntax",
  "use-memo",
]) {
  assert.equal(
    severity(`react-x/${duplicateRule}`),
    0,
    `react-x/${duplicateRule}가 canonical React Hooks 분석기와 중복됩니다.`,
  );
}
assert.equal(severity("react-x/no-missing-key"), 2);
assert.equal(severity("import-x/no-anonymous-default-export"), 1);

console.log("frontend ESLint effective config 계약 통과");
