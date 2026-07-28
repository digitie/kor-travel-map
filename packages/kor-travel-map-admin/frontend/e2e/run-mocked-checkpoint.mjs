import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const checkpoints = new Set(["A", "B", "C", "D"]);
const [checkpoint, ...playwrightArgs] = process.argv.slice(2);

if (!checkpoint || !checkpoints.has(checkpoint)) {
  console.error(
    "사용법: npm run e2e:mocked:checkpoint -- <A|B|C|D> [--workers=<양의 정수>]",
  );
  process.exit(2);
}

const unsafeArgs = playwrightArgs.filter(
  (argument) => !/^--workers=[1-9][0-9]*$/.test(argument),
);
if (unsafeArgs.length > 0) {
  console.error(
    "checkpoint는 전체 suite를 보존하는 --workers=<양의 정수> 외 Playwright 인자를 허용하지 않습니다.",
  );
  process.exit(2);
}

const revision = process.env.MOCKED_E2E_REVISION ?? process.env.GITHUB_SHA;
if (!revision || !/^[0-9a-f]{40}$/.test(revision)) {
  console.error(
    "MOCKED_E2E_REVISION 또는 GITHUB_SHA에 exact 40자 SHA가 필요합니다.",
  );
  process.exit(2);
}

const headResult = spawnSync("git", ["rev-parse", "HEAD"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
const headRevision = headResult.stdout?.trim();
if (
  headResult.status !== 0 ||
  !headRevision ||
  !/^[0-9a-f]{40}$/.test(headRevision)
) {
  console.error(
    "checkpoint 실행 worktree의 exact Git HEAD를 확인할 수 없습니다.",
  );
  process.exit(2);
}
if (revision !== headRevision) {
  console.error(
    `checkpoint revision이 Git HEAD와 다릅니다: declared=${revision}, head=${headRevision}`,
  );
  process.exit(2);
}
const statusResult = spawnSync(
  "git",
  ["status", "--porcelain", "--untracked-files=normal"],
  {
    cwd: process.cwd(),
    encoding: "utf8",
  },
);
if (statusResult.status !== 0 || statusResult.stdout.trim()) {
  console.error(
    "checkpoint는 tracked/untracked 변경이 없는 exact Git worktree에서만 실행할 수 있습니다.",
  );
  process.exit(2);
}

const require = createRequire(import.meta.url);
const playwrightCli = require.resolve("@playwright/test/cli");
const result = spawnSync(
  process.execPath,
  [
    playwrightCli,
    "test",
    ...playwrightArgs,
    "--reporter=list,./e2e/mocked-failure-reporter.ts",
  ],
  {
    env: {
      ...process.env,
      MOCKED_E2E_CHECKPOINT: checkpoint,
      MOCKED_E2E_REVISION: revision,
      MOCKED_E2E_VERIFIED_REVISION: headRevision,
    },
    stdio: "inherit",
  },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
