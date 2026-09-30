import { readFileSync } from "node:fs";

/** `user:password` 한 줄 — 출력 가능한 ASCII, user에는 `:`가 없다. */
const CREDENTIAL_PATTERN = /^[\x21-\x39\x3b-\x7e]+:[\x21-\x7e]+$/;

/**
 * C7 Dagster GraphQL client의 `Authorization` header.
 *
 * 공유 Dagster plane(Manager ADR-54 D2)의 공개 GraphQL은 Basic Auth gateway 뒤다. gateway는
 * Origin·Sec-Fetch-Site가 없는(브라우저가 아닌) POST에 유효한 Basic Auth가 있으면 받는다.
 * 자격증명은 러너가 root 전용 파일을 executor에 read-only로 붙인 경로
 * (`E2E_DAGSTER_BASIC_AUTH_FILE`)에서만 읽는다 — env·로그·evidence에 값이 없다.
 * 설정이 없으면 header도 없다(Map 전용 공개 URL은 인증이 없다).
 */
export function dagsterAuthorizationHeaders(): Record<string, string> {
  const path = process.env.E2E_DAGSTER_BASIC_AUTH_FILE;
  if (!path) return {};
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch {
    throw new Error("C7 Dagster Basic Auth 파일을 읽지 못했습니다 (values redacted)");
  }
  const credential = raw.replace(/\n$/, "");
  if (!CREDENTIAL_PATTERN.test(credential)) {
    throw new Error("C7 Dagster Basic Auth 파일 모양이 다릅니다 (values redacted)");
  }
  return {
    Authorization: `Basic ${Buffer.from(credential, "utf8").toString("base64")}`,
  };
}
