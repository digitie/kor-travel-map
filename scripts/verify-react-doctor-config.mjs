import { readFile } from "node:fs/promises";

const CONFIG_PATH = new URL("../doctor.config.json", import.meta.url);
const FRONTEND_PACKAGE_PATH = new URL(
  "../packages/kor-travel-map-admin/frontend/package.json",
  import.meta.url,
);
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

const [config, frontendPackage] = await Promise.all(
  [CONFIG_PATH, FRONTEND_PACKAGE_PATH].map(async (path) =>
    JSON.parse(await readFile(path, "utf8")),
  ),
);

if (JSON.stringify(config) !== JSON.stringify(EXPECTED_CONFIG)) {
  console.error(
    "React Doctor 설정은 검증된 전역 예외와 ops live transport 예외만 허용합니다.",
  );
  console.error("expected:", JSON.stringify(EXPECTED_CONFIG));
  console.error("actual:", JSON.stringify(config));
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
