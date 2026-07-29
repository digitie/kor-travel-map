import { createHash } from "node:crypto";
import {
  lstat,
  mkdir,
  readFile,
  readdir,
  readlink,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { frontendBuildInputs } from "./frontend-build-inputs.mjs";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const inputs = [
  ".dockerignore",
  ".npmrc",
  "package.json",
  "package-lock.json",
  "docker/frontend.Dockerfile",
  "scripts/frontend-build-inputs.mjs",
  "scripts/frontend-source-digest.mjs",
  "scripts/patch-redocly-openapi-core.mjs",
  "scripts/verify-next-sharp.mjs",
  "scripts/verify-npm-tree.mjs",
  "packages/map-marker-react",
  "packages/kor-travel-map-admin/frontend",
];
const buildInputs = frontendBuildInputs();
const excludedDirectories = new Set([
  ".cache",
  ".idea",
  ".next",
  ".turbo",
  ".vscode",
  "blob-report",
  "coverage",
  "node_modules",
  "out",
  "playwright-report",
  "test-results",
]);
const excludedFileNames = new Set([".DS_Store", "next-env.d.ts"]);
const generatedBuildInfo =
  "packages/kor-travel-map-admin/frontend/src/generated/frontend-build-info.ts";

async function collect(relativePath, files) {
  const absolutePath = path.join(repoRoot, relativePath);
  const stat = await lstat(absolutePath);
  if (stat.isDirectory()) {
    if (excludedDirectories.has(path.basename(relativePath))) return;
    const entries = await readdir(absolutePath);
    for (const entry of entries.toSorted()) {
      await collect(path.posix.join(relativePath, entry), files);
    }
    return;
  }
  if (relativePath === generatedBuildInfo) return;
  const fileName = path.basename(relativePath);
  if (
    excludedFileNames.has(fileName) ||
    ((fileName === ".env" || fileName.startsWith(".env.")) &&
      fileName !== ".env.example") ||
    fileName.endsWith(".local.md") ||
    fileName.endsWith(".tmp") ||
    fileName.endsWith(".tsbuildinfo") ||
    fileName === "types.ts.bak"
  ) {
    return;
  }
  if (!stat.isFile() && !stat.isSymbolicLink()) {
    throw new Error(`지원하지 않는 frontend digest 입력: ${relativePath}`);
  }
  files.push({ relativePath, symbolicLink: stat.isSymbolicLink() });
}

async function sourceDigest() {
  const files = [];
  for (const input of inputs) {
    await collect(input, files);
  }
  files.sort((left, right) =>
    left.relativePath.localeCompare(right.relativePath),
  );

  const hash = createHash("sha256");
  for (const [name, value] of buildInputs) {
    hash.update("build-arg");
    hash.update("\0");
    hash.update(name);
    hash.update("\0");
    hash.update(String(Buffer.byteLength(value)));
    hash.update("\0");
    hash.update(value);
    hash.update("\0");
  }
  for (const { relativePath, symbolicLink } of files) {
    const normalizedPath = relativePath.split(path.sep).join("/");
    const content = symbolicLink
      ? Buffer.from(
          `symlink:${await readlink(path.join(repoRoot, relativePath))}`,
        )
      : await readFile(path.join(repoRoot, relativePath));
    hash.update(normalizedPath);
    hash.update("\0");
    hash.update(String(content.byteLength));
    hash.update("\0");
    hash.update(content);
    hash.update("\0");
  }
  return hash.digest("hex");
}

const digest = await sourceDigest();
const writeIndex = process.argv.indexOf("--write");
if (writeIndex >= 0) {
  const output = process.argv.at(writeIndex + 1);
  if (!output || path.isAbsolute(output) || output.startsWith("..")) {
    throw new Error("--write에는 repo-relative 출력 경로가 필요합니다.");
  }
  const absoluteOutput = path.join(repoRoot, output);
  await mkdir(path.dirname(absoluteOutput), { recursive: true });
  await writeFile(
    absoluteOutput,
    `// Docker build가 frontend 입력 digest로 덮어쓴다.\n` +
      `export const FRONTEND_SOURCE_DIGEST = "${digest}";\n`,
    { encoding: "utf8", mode: 0o644 },
  );
} else {
  process.stdout.write(`${digest}\n`);
}
