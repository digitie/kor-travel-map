import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

// C7 Dagster GraphQL client — **읽기 전용**이다. queue worker job 정의와 queue sensor 상태,
// 그리고 feature update request 하나가 낳은 run의 identity·terminal status만 읽는다.
// mutation(sensor stop/start, launchRun …)은 두지 않는다: 2026-10-01 이전 KMA lane은
// sensor를 멈췄다 켜는 barrier를 썼지만, run이 sensor가 띄운 것이라는 사실은 run 자신의
// `dagster/sensor_name` tag가 증명하므로 공유 sensor를 건드릴 이유가 없다.

/**
 * Map code location selector — `docker/workspace.yaml`의 `location_name`이 정본이다
 * (`tests/unit/test_dagster_code_location_is_one_name.py`가 결박). 공유 Dagster plane에서
 * 다른 프로젝트의 repository·run을 읽지 않도록 조회와 대조를 이것으로 좁힌다.
 */
export const MAP_DAGSTER_LOCATION_NAME = "kortravelmap.dagster.definitions" as const;
const MAP_DAGSTER_REPOSITORY_SELECTOR = {
  repositoryName: "__repository__",
  repositoryLocationName: MAP_DAGSTER_LOCATION_NAME,
} as const;

/** `packages/kor-travel-map-dagster/.../sensors.py`의 queue worker job·sensor 이름. */
export const QUEUE_WORKER_JOB = "feature_update_request_worker" as const;
export const QUEUE_SENSOR_NAME = "feature_update_request_queue_sensor" as const;

/** worker run tag — `sensors.py::_tags_for_request`와 Dagster 자체 tag. */
const FEATURE_UPDATE_REQUEST_ID_TAG = "kor_travel_map.feature_update_request_id";
const FEATURE_UPDATE_REQUEST_GENERATION_TAG =
  "kor_travel_map.feature_update_request_generation";
const FEATURE_UPDATE_SCOPE_TYPE_TAG = "kor_travel_map.feature_update_scope_type";
const DAGSTER_SENSOR_NAME_TAG = "dagster/sensor_name";
const DAGSTER_CODE_LOCATION_TAG = "dagster/code_location";

const DAGSTER_GRAPHQL_TIMEOUT_MS = 15_000;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
/** `user:password` 한 줄 — 출력 가능한 ASCII, user에는 `:`가 없다. */
const CREDENTIAL_PATTERN = /^[\x21-\x39\x3b-\x7e]+:[\x21-\x7e]+$/;

const WORKER_PREFLIGHT_QUERY = `
query C7QueueWorkerPreflight(
  $repositorySelector: RepositorySelector!
  $sensorSelector: SensorSelector!
) {
  repositoryOrError(repositorySelector: $repositorySelector) {
    __typename
    ... on Repository {
      pipelines { name isJob }
    }
  }
  sensorOrError(sensorSelector: $sensorSelector) {
    __typename
    ... on Sensor {
      name
      sensorState { status }
    }
  }
}
`;

const WORKER_RUN_QUERY = `
query C7QueueWorkerRun($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run {
      runId
      jobName
      status
      tags { key value }
    }
  }
}
`;

type GraphqlEnvelope = { data?: unknown; errors?: unknown };

export type QueueWorkerRunIdentity = {
  generation: number;
  requestId: string;
  runId: string;
};

export type QueueWorkerRun = {
  sensorName: string;
  status: string;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/**
 * 공유 Dagster plane의 공개 GraphQL gateway(Manager ADR-54 D2)는 Basic Auth 뒤다. gateway는
 * Origin·Sec-Fetch-Site가 없는(브라우저가 아닌) POST에 유효한 Basic Auth가 있으면 받는다.
 * 자격증명은 러너가 root 전용 파일을 executor에 read-only로 붙인 경로
 * (`E2E_DAGSTER_BASIC_AUTH_FILE`)에서만 읽는다 — env·로그·evidence에 값이 없다.
 * 설정이 없으면 header도 없다(인증 없는 Map 전용 공개 URL).
 */
export function dagsterAuthorizationHeaders(): Record<string, string> {
  const credentialPath = process.env.E2E_DAGSTER_BASIC_AUTH_FILE;
  if (!credentialPath) return {};
  let raw: string;
  try {
    raw = readFileSync(credentialPath, "utf8");
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

/** caller가 선언한 hash와 같은 canonical `/graphql` endpoint만 돌려준다. */
export function dagsterGraphqlEndpoint(): URL {
  const expectedHash = process.env.E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256;
  const raw = process.env.E2E_DAGSTER_URL;
  if (!raw || !expectedHash || !SHA256_PATTERN.test(expectedHash)) {
    throw new Error(
      "C7 Dagster GraphQL endpoint/hash attestation이 필요합니다 (values redacted)",
    );
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("C7 Dagster GraphQL URL 형식이 올바르지 않습니다 (values redacted)");
  }
  if (
    url.protocol !== "https:" ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    throw new Error("C7 Dagster GraphQL URL은 credential/query/hash 없는 HTTPS여야 합니다");
  }
  const pathname = url.pathname.replace(/\/+$/, "");
  url.pathname = pathname.endsWith("/graphql") ? pathname : `${pathname}/graphql`;
  if (createHash("sha256").update(url.href, "utf8").digest("hex") !== expectedHash) {
    throw new Error(
      "C7 Dagster GraphQL endpoint attestation이 불일치합니다 (values redacted)",
    );
  }
  return url;
}

async function postDagsterGraphql(
  query: string,
  variables: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (/^\s*mutation\b/.test(query)) {
    throw new Error("C7 Dagster client는 읽기 전용이다");
  }
  let response: globalThis.Response;
  try {
    response = await fetch(dagsterGraphqlEndpoint(), {
      body: JSON.stringify({ query, variables }),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...dagsterAuthorizationHeaders(),
      },
      method: "POST",
      redirect: "error",
      signal: AbortSignal.timeout(DAGSTER_GRAPHQL_TIMEOUT_MS),
    });
  } catch {
    throw new Error("C7 Dagster GraphQL transport가 실패했습니다 (values redacted)");
  }
  if (!response.ok) {
    throw new Error(
      `C7 Dagster GraphQL HTTP 계약이 실패했습니다 (status=${response.status}, values redacted)`,
    );
  }
  let envelope: GraphqlEnvelope;
  try {
    envelope = (await response.json()) as GraphqlEnvelope;
  } catch {
    throw new Error("C7 Dagster GraphQL JSON 계약이 실패했습니다 (values redacted)");
  }
  if (Array.isArray(envelope.errors) && envelope.errors.length > 0) {
    throw new Error("C7 Dagster GraphQL 응답에 오류가 있습니다 (values redacted)");
  }
  const data = asRecord(envelope.data);
  if (data === null) {
    throw new Error("C7 Dagster GraphQL data 계약이 실패했습니다 (values redacted)");
  }
  return data;
}

/**
 * request를 만들기 전에 Map code location에 queue worker job이 정확히 하나 있고 queue
 * sensor가 RUNNING인지 읽는다. sensor가 멈춰 있으면 request가 queued로 남으므로 만들지
 * 않는다 — C7은 sensor를 켜지 않는다(운영자가 멈춘 데는 이유가 있다).
 */
export async function assertQueueWorkerOperational(): Promise<void> {
  const data = await postDagsterGraphql(WORKER_PREFLIGHT_QUERY, {
    repositorySelector: MAP_DAGSTER_REPOSITORY_SELECTOR,
    sensorSelector: {
      ...MAP_DAGSTER_REPOSITORY_SELECTOR,
      sensorName: QUEUE_SENSOR_NAME,
    },
  });
  const repository = asRecord(data.repositoryOrError);
  if (repository?.__typename !== "Repository") {
    throw new Error("C7 Dagster Map repository 조회 계약이 실패했습니다 (values redacted)");
  }
  const jobs = asArray(repository.pipelines)
    .map(asRecord)
    .filter((pipeline) => pipeline?.name === QUEUE_WORKER_JOB);
  if (jobs.length !== 1 || jobs[0]?.isJob !== true) {
    throw new Error("C7 Dagster queue worker job cardinality/isJob 계약이 실패했습니다");
  }
  const sensor = asRecord(data.sensorOrError);
  if (sensor?.__typename !== "Sensor" || sensor.name !== QUEUE_SENSOR_NAME) {
    throw new Error("C7 Dagster queue sensor 조회 계약이 실패했습니다 (values redacted)");
  }
  if (asRecord(sensor.sensorState)?.status !== "RUNNING") {
    throw new Error(
      "C7 Dagster queue sensor가 RUNNING이 아니다 — request를 만들지 않는다(C7은 sensor를 켜지 않는다)",
    );
  }
}

function runTags(value: unknown): Map<string, string> {
  const tags = new Map<string, string>();
  for (const raw of asArray(value)) {
    const tag = asRecord(raw);
    if (
      typeof tag?.key !== "string" ||
      !tag.key ||
      typeof tag.value !== "string" ||
      tags.has(tag.key)
    ) {
      throw new Error("C7 Dagster run tag 계약이 실패했습니다 (values redacted)");
    }
    tags.set(tag.key, tag.value);
  }
  return tags;
}

/**
 * request가 받은 Dagster run이 **Map code location의 queue sensor가 띄운 worker run**이고
 * 이 request·generation을 실행하는지 대조한 뒤 현재 run status를 돌려준다. run이 아직
 * 보이지 않으면 null이다(호출자가 bounded poll한다).
 */
export async function readQueueWorkerRun(
  identity: QueueWorkerRunIdentity,
): Promise<QueueWorkerRun | null> {
  const data = await postDagsterGraphql(WORKER_RUN_QUERY, { runId: identity.runId });
  const run = asRecord(data.runOrError);
  if (run?.__typename === "RunNotFoundError") return null;
  if (run?.__typename !== "Run") {
    throw new Error("C7 Dagster run 조회 계약이 실패했습니다 (values redacted)");
  }
  const tags = runTags(run.tags);
  const sensorName = tags.get(DAGSTER_SENSOR_NAME_TAG);
  if (
    run.runId !== identity.runId ||
    run.jobName !== QUEUE_WORKER_JOB ||
    tags.get(DAGSTER_CODE_LOCATION_TAG) !== MAP_DAGSTER_LOCATION_NAME ||
    tags.get(FEATURE_UPDATE_REQUEST_ID_TAG) !== identity.requestId ||
    tags.get(FEATURE_UPDATE_REQUEST_GENERATION_TAG) !== String(identity.generation) ||
    tags.get(FEATURE_UPDATE_SCOPE_TYPE_TAG) !== "provider_dataset" ||
    sensorName !== QUEUE_SENSOR_NAME ||
    typeof run.status !== "string"
  ) {
    throw new Error(
      "C7 Dagster run job/location/sensor/request tag identity 계약이 실패했습니다 (values redacted)",
    );
  }
  return { sensorName, status: run.status };
}
