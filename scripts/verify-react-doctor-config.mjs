import { access, readFile } from "node:fs/promises";

const REPOSITORY_ROOT = new URL("../", import.meta.url);
const FRONTEND_ROOT = new URL(
  "../packages/kor-travel-map-admin/frontend/",
  import.meta.url,
);
const CONFIG_PATH = new URL("doctor.config.json", FRONTEND_ROOT);
const ROOT_PACKAGE_PATH = new URL("package.json", REPOSITORY_ROOT);
const FRONTEND_PACKAGE_PATH = new URL(
  "package.json",
  FRONTEND_ROOT,
);
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
];
const EXPECTED_DOCTOR_COMMAND =
  "react-doctor --scope full --no-score --no-telemetry --no-respect-inline-disables --blocking warning .";
const EXPECTED_CONFIG = {
  ignore: {
    files: ["dist/**", "dev/**"],
    overrides: [
      {
        files: ["src/api/live.ts"],
        rules: [
          "react-doctor/effect-needs-cleanup",
          "react-doctor/no-fetch-in-effect",
        ],
      },
    ],
    rules: [
      "deslop/unused-file",
      "deslop/unused-dev-dependency",
      "react-doctor/exhaustive-deps",
      "react-doctor/no-event-handler",
      "react-doctor/advanced-event-handler-refs",
      "react-doctor/no-cascading-set-state",
      "react-doctor/rerender-state-only-in-handlers",
      "react-doctor/prefer-useReducer",
      "react-doctor/no-giant-component",
      "react-doctor/no-z-index-9999",
      "react-doctor/no-long-transition-duration",
      "react-doctor/no-render-in-render",
      "react-doctor/prefer-tag-over-role",
    ],
  },
};

const [config, rootPackage, frontendPackage] = await Promise.all(
  [CONFIG_PATH, ROOT_PACKAGE_PATH, FRONTEND_PACKAGE_PATH].map(async (path) =>
    JSON.parse(await readFile(path, "utf8")),
  ),
);

const forbiddenPaths = [
  ...CONFIG_FILENAMES.map((name) => new URL(name, REPOSITORY_ROOT)),
  ...CONFIG_FILENAMES.filter((name) => name !== "doctor.config.json").map(
    (name) => new URL(name, FRONTEND_ROOT),
  ),
  ...SUPPRESSION_FILENAMES.flatMap((name) => [
    new URL(name, REPOSITORY_ROOT),
    new URL(name, FRONTEND_ROOT),
  ]),
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

if (rootPackage.reactDoctor !== undefined || frontendPackage.reactDoctor !== undefined) {
  console.error("package.json#reactDoctor 설정은 canonical config를 가릴 수 없습니다.");
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
