import { readFile } from "node:fs/promises";

const CONFIG_PATH = new URL("../doctor.config.json", import.meta.url);
const EXPECTED_OVERRIDES = [
  {
    files: ["src/api/live.ts"],
    rules: [
      "react-doctor/effect-needs-cleanup",
      "react-doctor/no-fetch-in-effect",
    ],
  },
];

const config = JSON.parse(await readFile(CONFIG_PATH, "utf8"));
const overrides = config.ignore?.overrides;

if (JSON.stringify(overrides) !== JSON.stringify(EXPECTED_OVERRIDES)) {
  console.error(
    "React Doctor 예외는 검증된 ops live transport의 정확한 두 규칙만 허용합니다.",
  );
  console.error("expected:", JSON.stringify(EXPECTED_OVERRIDES));
  console.error("actual:", JSON.stringify(overrides));
  process.exit(1);
}

console.log("React Doctor 예외 범위가 정확합니다.");
