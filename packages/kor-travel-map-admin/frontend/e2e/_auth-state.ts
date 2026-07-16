import os from "node:os";
import path from "node:path";

const defaultRoot = path.join(os.tmpdir(), "kor-travel-map-playwright");

function storageStatePath(suite: "mocked" | "live"): string {
  return (
    process.env.E2E_STORAGE_STATE ??
    path.join(
      process.env.PLAYWRIGHT_ARTIFACT_ROOT ?? defaultRoot,
      `admin-frontend-${suite}`,
      "admin-state.json",
    )
  );
}

/** Mocked suite의 repo 밖 admin session state. */
export const MOCKED_STORAGE_STATE = storageStatePath("mocked");

/** Live suite의 repo 밖 admin session state. */
export const LIVE_STORAGE_STATE = storageStatePath("live");
