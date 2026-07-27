import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { ESLint } from "eslint";
import ts from "typescript";

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
const dataTablePath = path.join(
  frontend,
  "src",
  "components",
  "ui",
  "data-table.tsx",
);
const dataTableConfig = await eslint.calculateConfigForFile(dataTablePath);
const eslintConfigPath = path.join(frontend, "eslint.config.mjs");
const { default: eslintConfig } = await import(
  pathToFileURL(eslintConfigPath).href
);

function severity(ruleName, resolvedConfig = config) {
  const configured = resolvedConfig.rules?.[ruleName];
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
assert.equal(severity("react-hooks/incompatible-library"), 1);
assert.equal(severity("react-hooks/incompatible-library", dataTableConfig), 0);

const incompatibleLibraryOffOverrides = eslintConfig.filter((entry) => {
  const ruleSeverity = severity("react-hooks/incompatible-library", entry);
  return ruleSeverity === "off" || ruleSeverity === 0;
});
assert.equal(
  incompatibleLibraryOffOverrides.length,
  1,
  "incompatible-library off override는 exact allowlist 1개만 허용합니다.",
);
assert.deepEqual(
  incompatibleLibraryOffOverrides[0].files,
  ["src/components/ui/data-table.tsx"],
  "incompatible-library off 범위를 glob이나 추가 파일로 넓힐 수 없습니다.",
);

const scriptExtensions = new Set([
  ".cjs",
  ".cts",
  ".js",
  ".jsx",
  ".mjs",
  ".mts",
  ".ts",
  ".tsx",
]);
async function collectScriptFiles(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await collectScriptFiles(entryPath)));
    } else if (
      entry.isFile() &&
      scriptExtensions.has(path.extname(entry.name))
    ) {
      files.push(path.resolve(entryPath));
    }
  }
  return files;
}

const frontendSourcePaths = [
  ...(await collectScriptFiles(path.join(frontend, "src"))),
  ...(await collectScriptFiles(path.join(frontend, "e2e"))),
].sort();
const expectedLintFilePaths = new Set(frontendSourcePaths);
assert.equal(
  expectedLintFilePaths.size,
  frontendSourcePaths.length,
  "frontend lint 대상 파일 경로는 중복될 수 없습니다.",
);

const dataTableSource = await readFile(dataTablePath, "utf8");
const dataTableLines = dataTableSource.split("\n");
assert.equal(
  dataTableLines.filter((line) => line.trim() === '"use no memo"').length,
  2,
  "DataTable과 VirtualizedTable만 React Compiler opt-out이어야 합니다.",
);
assert.equal(dataTableSource.split("useReactTable(").length - 1, 1);
assert.equal(dataTableSource.split("useVirtualizer(").length - 1, 1);

function functionOwner(node, parsedSource) {
  if (node.name && "text" in node.name) {
    return node.name.text;
  }
  if (
    ts.isVariableDeclaration(node.parent) &&
    ts.isIdentifier(node.parent.name)
  ) {
    return node.parent.name.text;
  }
  const position = parsedSource.getLineAndCharacterOfPosition(
    node.getStart(parsedSource),
  );
  return `<anonymous@${position.line + 1}:${position.character + 1}>`;
}

const compilerOptOutDirectives = new Set(["use no forget", "use no memo"]);

function collectCompilerOptOuts(statements) {
  const directives = [];
  for (const statement of statements) {
    if (
      !ts.isExpressionStatement(statement) ||
      !ts.isStringLiteral(statement.expression)
    ) {
      break;
    }
    if (compilerOptOutDirectives.has(statement.expression.text)) {
      directives.push(statement.expression.text);
    }
  }
  return directives;
}

function scriptKind(sourcePath) {
  if (sourcePath.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (sourcePath.endsWith(".jsx")) return ts.ScriptKind.JSX;
  if (
    sourcePath.endsWith(".js") ||
    sourcePath.endsWith(".mjs") ||
    sourcePath.endsWith(".cjs")
  ) {
    return ts.ScriptKind.JS;
  }
  return ts.ScriptKind.TS;
}

const boundaryFunctions = new Map();
const compilerBoundaries = [];
let sourceFile;
for (const sourcePath of frontendSourcePaths) {
  const source =
    sourcePath === dataTablePath
      ? dataTableSource
      : await readFile(sourcePath, "utf8");
  const parsedSource = ts.createSourceFile(
    sourcePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    scriptKind(sourcePath),
  );
  if (sourcePath === dataTablePath) {
    sourceFile = parsedSource;
  }
  const relativePath = path
    .relative(frontend, sourcePath)
    .split(path.sep)
    .join("/");
  for (const directive of collectCompilerOptOuts(parsedSource.statements)) {
    compilerBoundaries.push({
      filePath: relativePath,
      owner: "<module>",
      directive,
    });
  }
  function visit(node) {
    if (ts.isFunctionLike(node) && node.body && ts.isBlock(node.body)) {
      for (const directive of collectCompilerOptOuts(node.body.statements)) {
        const owner = functionOwner(node, parsedSource);
        compilerBoundaries.push({
          filePath: relativePath,
          owner,
          directive,
        });
        if (sourcePath === dataTablePath && directive === "use no memo") {
          boundaryFunctions.set(owner, node);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(parsedSource);
}
assert.deepEqual(
  compilerBoundaries.sort(
    (left, right) =>
      left.filePath.localeCompare(right.filePath) ||
      left.owner.localeCompare(right.owner),
  ),
  [
    {
      filePath: "src/components/ui/data-table.tsx",
      owner: "DataTable",
      directive: "use no memo",
    },
    {
      filePath: "src/components/ui/data-table.tsx",
      owner: "VirtualizedTable",
      directive: "use no memo",
    },
  ],
  "module/function React Compiler opt-out은 TanStack hook 소유 함수 두 개만 허용합니다.",
);
assert.ok(sourceFile, "data-table.tsx TypeScript AST가 필요합니다.");

function ownedCallPositions(functionNode, callName) {
  const positions = [];
  function visit(node) {
    if (node !== functionNode && ts.isFunctionLike(node)) return;
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === callName
    ) {
      const position = sourceFile.getLineAndCharacterOfPosition(
        node.expression.getStart(sourceFile),
      );
      positions.push({
        line: position.line + 1,
        column: position.character + 1,
      });
    }
    ts.forEachChild(node, visit);
  }
  visit(functionNode);
  return positions;
}

const expectedTanstackDiagnostics = [
  ...ownedCallPositions(boundaryFunctions.get("DataTable"), "useReactTable"),
  ...ownedCallPositions(
    boundaryFunctions.get("VirtualizedTable"),
    "useVirtualizer",
  ),
].sort((a, b) => a.line - b.line || a.column - b.column);
assert.equal(
  expectedTanstackDiagnostics.length,
  2,
  "각 opt-out 함수가 자신의 TanStack hook을 정확히 하나씩 소유해야 합니다.",
);

const diagnosticEslint = new ESLint({
  cwd: frontend,
  allowInlineConfig: false,
  overrideConfig: {
    rules: { "react-hooks/incompatible-library": "warn" },
  },
});
const diagnosticResults = await diagnosticEslint.lintFiles([
  "src/**/*.{cjs,cts,js,jsx,mjs,mts,ts,tsx}",
  "e2e/**/*.{cjs,cts,js,jsx,mjs,mts,ts,tsx}",
]);
const diagnosticResult = diagnosticResults.find(
  (result) => result.filePath === dataTablePath,
);
const suppressionEslint = new ESLint({
  cwd: frontend,
  overrideConfig: {
    rules: { "react-hooks/incompatible-library": "warn" },
  },
});
const suppressionResults = await suppressionEslint.lintFiles([
  "src/**/*.{cjs,cts,js,jsx,mjs,mts,ts,tsx}",
  "e2e/**/*.{cjs,cts,js,jsx,mjs,mts,ts,tsx}",
]);

function assertLintFileSet(results, label) {
  const actual = [
    ...new Set(results.map((result) => path.resolve(result.filePath))),
  ].sort();
  assert.deepEqual(
    actual,
    frontendSourcePaths,
    `${label}가 src/e2e TypeScript 파일을 ignore하거나 추가할 수 없습니다.`,
  );
}

assertLintFileSet(diagnosticResults, "inline config 비활성 lint");
assertLintFileSet(suppressionResults, "suppression 탐지 lint");
assert.ok(
  diagnosticResult,
  "data-table.tsx의 incompatible-library diagnostic 결과가 필요합니다.",
);
const actualTanstackDiagnostics = diagnosticResult.messages
  .filter((message) => message.ruleId === "react-hooks/incompatible-library")
  .map(({ line, column }) => ({ line, column }))
  .sort((a, b) => a.line - b.line || a.column - b.column);
assert.deepEqual(
  diagnosticResults.flatMap((result) =>
    result.messages
      .filter(
        (message) =>
          message.ruleId === "react-hooks/incompatible-library" &&
          result.filePath !== dataTablePath,
      )
      .map((message) => ({ filePath: result.filePath, message })),
  ),
  [],
  "data-table.tsx 밖에 incompatible-library hook이나 inline 우회를 추가할 수 없습니다.",
);
assert.deepEqual(
  actualTanstackDiagnostics,
  expectedTanstackDiagnostics,
  "TanStack incompatible hook 추가·이동 시 exact compiler boundary를 함께 검토해야 합니다.",
);
const incompatibleSuppressions = suppressionResults.flatMap((result) =>
  result.suppressedMessages.filter(
    (message) => message.ruleId === "react-hooks/incompatible-library",
  ),
);
assert.equal(
  incompatibleSuppressions.length,
  0,
  "frontend 전체에서 incompatible-library inline suppression을 허용하지 않습니다.",
);
assert.equal(
  dataTableSource.includes(
    "eslint-disable-next-line react-hooks/incompatible-library",
  ),
  false,
  "TanStack compiler 경계는 inline suppression 대신 exact config allowlist로 관리합니다.",
);
console.log("frontend ESLint effective config 계약 통과");
