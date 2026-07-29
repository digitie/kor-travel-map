import { access, readFile } from "node:fs/promises";

const REPOSITORY_ROOT = new URL("../", import.meta.url);
const FRONTEND_ROOT = new URL(
  "../packages/kor-travel-map-admin/frontend/",
  import.meta.url,
);
const CONFIG_PATH = new URL("doctor.config.json", FRONTEND_ROOT);
const ROOT_PACKAGE_PATH = new URL("package.json", REPOSITORY_ROOT);
const FRONTEND_PACKAGE_PATH = new URL("package.json", FRONTEND_ROOT);
const ROOT_GITATTRIBUTES_PATH = new URL(".gitattributes", REPOSITORY_ROOT);
const FRONTEND_GITIGNORE_PATH = new URL(".gitignore", FRONTEND_ROOT);
const CONFIG_FILENAMES = [
  "doctor.config.ts",
  "doctor.config.mts",
  "doctor.config.cts",
  "doctor.config.js",
  "doctor.config.mjs",
  "doctor.config.cjs",
  "doctor.config.json",
  "doctor.config.jsonc",
  "react-doctor.config.json",
];
const SUPPRESSION_FILENAMES = [
  ".oxlintignore",
  ".eslintignore",
  ".prettierignore",
  "knip.json",
  "knip.jsonc",
];
const EXPECTED_DOCTOR_COMMAND =
  "react-doctor --scope full --no-score --no-telemetry --no-respect-inline-disables --blocking warning .";
const EXPECTED_CONFIG = {
  ignore: {
    files: ["dist/**"],
    overrides: [
      {
        files: ["src/api/live.ts"],
        rules: [
          "react-doctor/effect-needs-cleanup",
          "react-doctor/no-fetch-in-effect",
        ],
      },
      {
        files: ["src/app/ops/datasets/datasets-client.tsx"],
        rules: ["react-doctor/no-event-handler"],
      },
    ],
  },
};
const EXPECTED_ROOT_GITATTRIBUTES = `* text=auto eol=lf

# Binary
*.docx binary
*.xlsx binary
*.pdf binary
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.zip binary
*.gz binary
*.tar binary
*.sqlite binary
*.db binary

# Force LF for shell/sql
*.sh text eol=lf
*.sql text eol=lf
*.py text eol=lf
`;
const EXPECTED_FRONTEND_GITIGNORE = `node_modules/
.env
.env.local
.env.*.local
!.env.example

# Next.js
.next/
out/
next-env.d.ts

# tsc --noEmit incremental build cache (CI gate, PR#93)
*.tsbuildinfo

# editor
.vscode/
.idea/

# logs
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*
pnpm-debug.log*

# typegen drift snapshot
src/api/types.ts.bak

# turbo / build cache
.turbo/

# playwright e2e (#117)
test-results/
playwright-report/
playwright/.cache/
blob-report/
`;

const [
  config,
  rootPackage,
  frontendPackage,
  rootGitattributes,
  frontendGitignore,
] = await Promise.all([
  ...[CONFIG_PATH, ROOT_PACKAGE_PATH, FRONTEND_PACKAGE_PATH].map(async (path) =>
    JSON.parse(await readFile(path, "utf8")),
  ),
  readFile(ROOT_GITATTRIBUTES_PATH, "utf8"),
  readFile(FRONTEND_GITIGNORE_PATH, "utf8"),
]);

const forbiddenPaths = [
  ...CONFIG_FILENAMES.map((name) => new URL(name, REPOSITORY_ROOT)),
  ...CONFIG_FILENAMES.filter((name) => name !== "doctor.config.json").map(
    (name) => new URL(name, FRONTEND_ROOT),
  ),
  ...SUPPRESSION_FILENAMES.flatMap((name) => [
    new URL(name, REPOSITORY_ROOT),
    new URL(name, FRONTEND_ROOT),
  ]),
  new URL(".gitattributes", FRONTEND_ROOT),
];
const existingForbiddenPaths = [];
for (const path of forbiddenPaths) {
  try {
    await access(path);
    existingForbiddenPaths.push(path.pathname);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

if (existingForbiddenPaths.length > 0) {
  console.error(
    "React Doctor canonical 설정을 가리거나 우회하는 추가 설정 파일은 허용하지 않습니다.",
  );
  console.error("forbidden:", JSON.stringify(existingForbiddenPaths));
  process.exit(1);
}

if (JSON.stringify(config) !== JSON.stringify(EXPECTED_CONFIG)) {
  console.error(
    "React Doctor 설정은 검증된 전역 예외와 ops live transport 예외만 허용합니다.",
  );
  console.error("expected:", JSON.stringify(EXPECTED_CONFIG));
  console.error("actual:", JSON.stringify(config));
  process.exit(1);
}

if (
  rootPackage.reactDoctor !== undefined ||
  frontendPackage.reactDoctor !== undefined ||
  rootPackage.knip !== undefined ||
  frontendPackage.knip !== undefined
) {
  console.error(
    "package.json#reactDoctor/knip 설정은 canonical 분석 범위를 가릴 수 없습니다.",
  );
  process.exit(1);
}

if (
  rootGitattributes !== EXPECTED_ROOT_GITATTRIBUTES ||
  frontendGitignore !== EXPECTED_FRONTEND_GITIGNORE
) {
  console.error(
    "React Doctor가 읽는 .gitattributes/.gitignore는 검증된 exact 내용이어야 합니다.",
  );
  process.exit(1);
}

if (frontendPackage.scripts?.doctor !== EXPECTED_DOCTOR_COMMAND) {
  console.error(
    "React Doctor 명령은 full scope·warning 차단·인라인 suppression 무시 계약을 유지해야 합니다.",
  );
  console.error("expected:", EXPECTED_DOCTOR_COMMAND);
  console.error("actual:", frontendPackage.scripts?.doctor);
  process.exit(1);
}

console.log("React Doctor 예외 범위가 정확합니다.");
