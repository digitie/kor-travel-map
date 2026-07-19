import type {
  FullConfig,
  FullResult,
  Reporter,
  Suite,
  TestCase,
  TestResult,
} from "@playwright/test/reporter";
import fs from "node:fs";
import path from "node:path";

type RedactedResult = {
  durationMs: number;
  sequence: number;
  spec: string;
  status: string;
};

type ReporterOptions = {
  outputFolder: string;
};

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

/**
 * C7 evidence 전용 reporter.
 *
 * URL, request/target/run ID, assertion value, stdout/stderr, error stack와 attachment
 * 경로를 기록하지 않고 spec basename·상태·소요 시간만 남긴다.
 */
export default class C7RedactedReporter implements Reporter {
  readonly #outputFolder: string;
  readonly #results: RedactedResult[] = [];
  #total = 0;

  constructor(options: ReporterOptions) {
    this.#outputFolder = options.outputFolder;
  }

  onBegin(_config: FullConfig, suite: Suite): void {
    this.#total = suite.allTests().length;
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    this.#results.push({
      durationMs: Math.max(0, Math.trunc(result.duration)),
      sequence: this.#results.length + 1,
      spec: path.basename(test.location.file),
      status: result.status,
    });
  }

  onEnd(fullResult: FullResult): void {
    fs.mkdirSync(this.#outputFolder, { mode: 0o700, recursive: true });
    fs.chmodSync(this.#outputFolder, 0o700);
    const counts = new Map<string, number>();
    for (const result of this.#results) {
      counts.set(result.status, (counts.get(result.status) ?? 0) + 1);
    }
    const summary = {
      counts: Object.fromEntries([...counts.entries()].sort()),
      result: fullResult.status,
      testsObserved: this.#results.length,
      testsPlanned: this.#total,
      version: 1,
    };
    const jsonPath = path.join(this.#outputFolder, "c7-summary.json");
    fs.writeFileSync(jsonPath, `${JSON.stringify(summary)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });

    const cases = this.#results
      .map((result) => {
        const failed = result.status === "passed" ? "" : "<failure/>";
        return (
          `<testcase classname="c7-redacted" name="${escapeXml(result.spec)}#${result.sequence}" ` +
          `time="${(result.durationMs / 1000).toFixed(3)}">${failed}</testcase>`
        );
      })
      .join("");
    const junitPath = path.join(this.#outputFolder, "c7-results.xml");
    fs.writeFileSync(
      junitPath,
      `<?xml version="1.0" encoding="UTF-8"?><testsuite tests="${this.#results.length}">${cases}</testsuite>\n`,
      { encoding: "utf8", mode: 0o600 },
    );

    const rows = this.#results
      .map(
        (result) =>
          `<tr><td>${result.sequence}</td><td>${escapeXml(result.spec)}</td>` +
          `<td>${escapeXml(result.status)}</td><td>${result.durationMs}</td></tr>`,
      )
      .join("");
    const htmlPath = path.join(this.#outputFolder, "c7-summary.html");
    fs.writeFileSync(
      htmlPath,
      "<!doctype html><html lang=\"ko\"><meta charset=\"utf-8\">" +
        "<title>C7 redacted result</title><body><h1>C7 redacted result</h1>" +
        `<p>result=${escapeXml(fullResult.status)} planned=${this.#total} observed=${this.#results.length}</p>` +
        "<table><thead><tr><th>#</th><th>spec</th><th>status</th><th>duration_ms</th></tr></thead>" +
        `<tbody>${rows}</tbody></table></body></html>\n`,
      { encoding: "utf8", mode: 0o600 },
    );
  }
}
