import type { Page } from "@playwright/test";
import {
  chmodSync,
  mkdtempSync,
  mkdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { removeStorageState } from "../e2e/_auth-state";
import { authenticateAdmin } from "../e2e/auth-session";

const temporaryRoots: string[] = [];

afterEach(() => {
  delete process.env.E2E_ADMIN_PASSWORD;
  for (const root of temporaryRoots.splice(0)) {
    rmSync(root, { force: true, recursive: true });
  }
});

describe("Playwright admin storage state security", () => {
  it("빈 storage state도 private directory와 0600 파일로 저장한다", async () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "ktm-auth-state-test-"));
    temporaryRoots.push(root);
    const directory = path.join(root, "nested");
    const storageState = path.join(directory, "admin-state.json");
    const page = {
      context: () => ({
        storageState: async ({ path: target }: { path: string }) => {
          writeFileSync(target, "{}");
        },
      }),
    } as unknown as Page;

    await authenticateAdmin(page, storageState);

    expect(statSync(directory).mode & 0o777).toBe(0o700);
    expect(statSync(storageState).mode & 0o777).toBe(0o600);
  });

  it("기존 directory 권한은 건드리지 않고 teardown은 state만 제거한다", async () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "ktm-auth-state-test-"));
    temporaryRoots.push(root);
    const directory = path.join(root, "existing");
    const storageState = path.join(directory, "admin-state.json");
    mkdirSync(directory, { mode: 0o775 });
    chmodSync(directory, 0o775);
    writeFileSync(storageState, "{}");

    const page = {
      context: () => ({
        storageState: async ({ path: target }: { path: string }) => {
          writeFileSync(target, "{}");
        },
      }),
    } as unknown as Page;
    await authenticateAdmin(page, storageState);
    removeStorageState(storageState);

    expect(statSync(directory).mode & 0o777).toBe(0o775);
    expect(() => statSync(storageState)).toThrow();
  });
});
