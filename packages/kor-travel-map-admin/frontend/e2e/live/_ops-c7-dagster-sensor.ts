import { createHash, randomUUID } from "node:crypto";
import {
  chmod,
  mkdir,
  open,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import path from "node:path";

const QUEUE_SENSOR_NAME = "feature_update_request_queue_sensor";
const DEFAULT_OPERATION_TIMEOUT_MS = 90_000;
const DEFAULT_POLL_INTERVAL_MS = 1_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 15_000;
const QUIESCENCE_SAFETY_MARGIN_MS = 2_000;

const SENSOR_DISCOVERY_QUERY = `
query C7QueueSensorDiscovery {
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        name
        location { name }
        sensors { name }
      }
    }
  }
}
`;

const SENSOR_STATUS_QUERY = `
query C7QueueSensorStatus($selector: SensorSelector!) {
  sensorOrError(sensorSelector: $selector) {
    __typename
    ... on Sensor {
      name
      defaultStatus
      canReset
      minIntervalSeconds
      sensorState {
        id
        selectorId
        status
        repositoryName
        repositoryLocationName
        ticks(limit: 10, statuses: [STARTED]) {
          tickId
          status
          timestamp
          endTimestamp
        }
      }
    }
  }
}
`;

const START_SENSOR_MUTATION = `
mutation C7StartQueueSensor($selector: SensorSelector!) {
  startSensor(sensorSelector: $selector) {
    __typename
    ... on Sensor { name }
  }
}
`;

const STOP_SENSOR_MUTATION = `
mutation C7StopQueueSensor($id: String!) {
  stopSensor(id: $id) {
    __typename
    ... on StopSensorMutationResult {
      instigationState { status }
    }
  }
}
`;

const RESET_SENSOR_MUTATION = `
mutation C7ResetQueueSensor($selector: SensorSelector!) {
  resetSensor(sensorSelector: $selector) {
    __typename
    ... on Sensor { name }
  }
}
`;

export type QueueSensorStatus = "RUNNING" | "STOPPED";

export type QueueSensorSelector = {
  repositoryLocationName: string;
  repositoryName: string;
  sensorName: string;
};

export type QueueSensorSnapshot = {
  canReset: boolean;
  defaultStatus: QueueSensorStatus;
  minIntervalSeconds: number;
  selector: QueueSensorSelector;
  selectorId: string;
  sensorId: string;
  status: QueueSensorStatus;
};

export type QueueSensorControllerOptions = {
  dagsterUrl?: string;
  operationTimeoutMs?: number;
  pollIntervalMs?: number;
  requestTimeoutMs?: number;
  sensorName?: string;
  stateFile?: string;
};

type SensorObservation = QueueSensorSnapshot & {
  startedTickCount: number;
};

type SensorMutationIntent = {
  before: QueueSensorSnapshot;
  intendedAfter: QueueSensorSnapshot;
  operation: string;
};

type PersistedSensorState = {
  dagsterGraphqlEndpointSha256: string;
  expectedDagsterGraphqlEndpointSha256: string;
  initialSensor: QueueSensorSnapshot;
  mutationIntent: SensorMutationIntent | null;
  observedSensor: QueueSensorSnapshot;
  ownedExpectedSensor: QueueSensorSnapshot;
  phase:
    | "snapshotted"
    | "stopping"
    | "stopped_quiescent"
    | "starting"
    | "running"
    | "restoring"
    | "restored"
    | "restore_failed";
  updatedAt: string;
  version: 3;
};

type GraphqlEnvelope = {
  data?: unknown;
  errors?: unknown;
};

export class QueueSensorController {
  readonly #graphqlUrl: URL;
  readonly #graphqlUrlSha256: string;
  readonly #expectedGraphqlUrlSha256: string;
  readonly #operationTimeoutMs: number;
  readonly #pollIntervalMs: number;
  readonly #requestTimeoutMs: number;
  readonly #sensorName: string;
  readonly #stateFile: string | null;
  #initialSnapshot: QueueSensorSnapshot | null = null;
  #mutationIntent: SensorMutationIntent | null = null;
  #ownedExpectedSnapshot: QueueSensorSnapshot | null = null;
  #selector: QueueSensorSelector | null = null;

  constructor(options: QueueSensorControllerOptions = {}) {
    this.#graphqlUrl = graphqlEndpoint(
      options.dagsterUrl ?? process.env.E2E_DAGSTER_URL,
    );
    this.#graphqlUrlSha256 = createHash("sha256")
      .update(this.#graphqlUrl.href)
      .digest("hex");
    this.#expectedGraphqlUrlSha256 = lowercaseSha256(
      process.env.E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256,
      "expected_dagster_origin_sha256",
    );
    this.#assertEndpointAttestation("configuration");
    this.#operationTimeoutMs = positiveInteger(
      options.operationTimeoutMs ?? DEFAULT_OPERATION_TIMEOUT_MS,
      "operation_timeout",
    );
    this.#pollIntervalMs = positiveInteger(
      options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS,
      "poll_interval",
    );
    this.#requestTimeoutMs = positiveInteger(
      options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS,
      "request_timeout",
    );
    this.#sensorName = options.sensorName ?? QUEUE_SENSOR_NAME;
    this.#stateFile = stateFilePath(
      options.stateFile ?? process.env.E2E_C7_ORCHESTRATOR_STATE_FILE,
    );
  }

  async initialize(): Promise<void> {
    this.#selector = await this.#discoverSelector();
  }

  async captureSnapshot(): Promise<QueueSensorSnapshot> {
    await this.#assertStateFileClaimable();
    const snapshot = withoutTicks(await this.#observe());
    this.#initialSnapshot = snapshot;
    this.#ownedExpectedSnapshot = snapshot;
    await this.#persist("snapshotted", snapshot);
    return snapshot;
  }

  async stopAndWaitForQuiescence(
    initial: QueueSensorSnapshot,
  ): Promise<QueueSensorSnapshot> {
    this.#requireMutationStateFile("stop_sensor");
    this.#assertSameSelector(initial.selector);
    this.#assertEndpointAttestation("stop_sensor");

    const current = await this.#observe();
    this.#assertOwnedExpected(current, "stop_sensor");
    let snapshot = withoutTicks(current);
    if (current.status !== "STOPPED") {
      const before = withoutTicks(current);
      const intendedAfter = withSensorStatus(before, "STOPPED");
      snapshot = await this.#mutateOwnedSensor(
        "stopping",
        "stop_sensor",
        STOP_SENSOR_MUTATION,
        { id: current.sensorId },
        "stopSensor",
        "StopSensorMutationResult",
        before,
        intendedAfter,
        () => this.#waitForStatus("STOPPED", "stop_sensor"),
      );
    }
    snapshot = await this.#waitForStoppedQuiescence(
      initial.minIntervalSeconds,
      "stop_sensor",
    );
    if (
      !sameOperationalSnapshot(
        snapshot,
        withSensorStatus(withoutTicks(current), "STOPPED"),
      )
    ) {
      throw sensorError("CONCURRENT_SENSOR_DRIFT", "stop_sensor");
    }
    this.#ownedExpectedSnapshot = snapshot;
    this.#mutationIntent = null;
    await this.#persist("stopped_quiescent", snapshot);
    return snapshot;
  }

  async start(): Promise<QueueSensorSnapshot> {
    this.#requireMutationStateFile("start_sensor");
    this.#assertEndpointAttestation("start_sensor");
    const before = await this.#observe();
    this.#assertOwnedExpected(before, "start_sensor");
    let running = withoutTicks(before);
    if (before.status !== "RUNNING") {
      const beforeSnapshot = withoutTicks(before);
      running = await this.#mutateOwnedSensor(
        "starting",
        "start_sensor",
        START_SENSOR_MUTATION,
        { selector: this.#requireSelector() },
        "startSensor",
        "Sensor",
        beforeSnapshot,
        withSensorStatus(beforeSnapshot, "RUNNING"),
        () => this.#waitForStatus("RUNNING", "start_sensor"),
      );
    }
    this.#ownedExpectedSnapshot = running;
    this.#mutationIntent = null;
    await this.#persist("running", running);
    return running;
  }

  async restore(initial: QueueSensorSnapshot): Promise<QueueSensorSnapshot> {
    this.#requireMutationStateFile("restore_sensor");
    this.#assertSameSelector(initial.selector);
    this.#assertEndpointAttestation("restore_sensor");
    await this.#resolveUncertainMutationBeforeRestore();
    const failures: unknown[] = [];
    await this.#persist(
      "restoring",
      this.#ownedExpectedSnapshot ?? initial,
    ).catch((error: unknown) => {
      failures.push(error);
    });

    let remoteRestoreAllowed = true;
    let current: QueueSensorSnapshot | null = null;
    try {
      const observed = await this.#observe();
      this.#assertOwnedExpected(observed, "restore_sensor");
      current = withoutTicks(observed);
    } catch (error) {
      failures.push(error);
      remoteRestoreAllowed = false;
    }

    if (remoteRestoreAllowed) {
      try {
        if (!current) {
          throw sensorError("MISSING_OWNED_SNAPSHOT", "restore_sensor");
        }
        if (!initial.canReset) {
          if (!sameOperationalSnapshot(current, initial)) {
            const before = current;
            current = await this.#mutateOwnedSensor(
              "restoring",
              "reset_sensor",
              RESET_SENSOR_MUTATION,
              { selector: initial.selector },
              "resetSensor",
              "Sensor",
              before,
              {
                ...before,
                canReset: false,
                status: before.defaultStatus,
              },
              () => this.#waitForStatus(before.defaultStatus, "reset_sensor"),
            );
          }
        } else {
          if (!current.canReset && current.status === initial.status) {
            const opposite = initial.status === "RUNNING" ? "STOPPED" : "RUNNING";
            const before = current;
            current = await this.#mutateOwnedSensor(
              "restoring",
              "restore_cycle_sensor",
              opposite === "RUNNING" ? START_SENSOR_MUTATION : STOP_SENSOR_MUTATION,
              opposite === "RUNNING"
                ? { selector: initial.selector }
                : { id: before.sensorId },
              opposite === "RUNNING" ? "startSensor" : "stopSensor",
              opposite === "RUNNING" ? "Sensor" : "StopSensorMutationResult",
              before,
              withSensorStatus(before, opposite),
              () =>
                opposite === "RUNNING"
                  ? this.#waitForStatus("RUNNING", "restore_cycle_sensor")
                  : this.#waitForStoppedQuiescence(
                      initial.minIntervalSeconds,
                      "restore_cycle_sensor",
                    ),
            );
          }
          if (!sameOperationalSnapshot(current, initial)) {
            const before = current;
            current = await this.#mutateOwnedSensor(
              "restoring",
              "restore_sensor_status",
              initial.status === "RUNNING"
                ? START_SENSOR_MUTATION
                : STOP_SENSOR_MUTATION,
              initial.status === "RUNNING"
                ? { selector: initial.selector }
                : { id: before.sensorId },
              initial.status === "RUNNING" ? "startSensor" : "stopSensor",
              initial.status === "RUNNING" ? "Sensor" : "StopSensorMutationResult",
              before,
              withSensorStatus(before, initial.status),
              () =>
                initial.status === "RUNNING"
                  ? this.#waitForStatus("RUNNING", "restore_sensor_status")
                  : this.#waitForStoppedQuiescence(
                      initial.minIntervalSeconds,
                      "restore_sensor_status",
                    ),
            );
          }
        }
      } catch (error) {
        failures.push(error);
      }
    }

    let restored: QueueSensorSnapshot | null = null;
    try {
      restored = remoteRestoreAllowed
        ? initial.status === "STOPPED"
          ? await this.#waitForStoppedQuiescence(
              initial.minIntervalSeconds,
              "restore_sensor",
            )
          : await this.#waitForStatus(initial.status, "restore_sensor")
        : withoutTicks(await this.#observe());
      if (!sameOperationalSnapshot(restored, initial)) {
        throw sensorError("RESTORE_MISMATCH", "restore_sensor");
      }
    } catch (error) {
      failures.push(error);
    }

    if (this.#mutationIntent) {
      failures.push(
        sensorError(
          "MUTATION_OUTCOME_UNCERTAIN",
          this.#mutationIntent.operation,
        ),
      );
    }
    if (restored && failures.length === 0) {
      this.#ownedExpectedSnapshot = restored;
      this.#mutationIntent = null;
      await this.#persist("restored", restored).catch((error: unknown) => {
        failures.push(error);
      });
    }
    if (failures.length > 0 || !restored) {
      await this.#persist("restore_failed", restored ?? initial).catch(
        (error: unknown) => {
          failures.push(error);
        },
      );
      throw sensorError(
        "RESTORE_FAILED",
        `restore_sensor_failures_${failures.length}`,
      );
    }
    return restored;
  }

  async #discoverSelector(): Promise<QueueSensorSelector> {
    const data = await this.#postGraphql(
      "discover_sensor",
      SENSOR_DISCOVERY_QUERY,
      {},
    );
    const root = asRecord(data.repositoriesOrError);
    if (root?.__typename !== "RepositoryConnection") {
      throw sensorError("DISCOVERY_RESULT_ERROR", "discover_sensor", root?.__typename);
    }

    const matches: QueueSensorSelector[] = [];
    for (const nodeValue of asArray(root.nodes)) {
      const node = asRecord(nodeValue);
      const repositoryName = stringValue(node?.name);
      const locationName = stringValue(asRecord(node?.location)?.name);
      if (!repositoryName || !locationName) continue;
      for (const sensorValue of asArray(node?.sensors)) {
        const sensorName = stringValue(asRecord(sensorValue)?.name);
        if (sensorName === this.#sensorName) {
          matches.push({
            repositoryLocationName: locationName,
            repositoryName,
            sensorName,
          });
        }
      }
    }
    if (matches.length !== 1) {
      throw sensorError("SENSOR_CARDINALITY", "discover_sensor");
    }
    return matches[0] as QueueSensorSelector;
  }

  async #observe(): Promise<SensorObservation> {
    const selector = this.#requireSelector();
    const data = await this.#postGraphql(
      "query_sensor",
      SENSOR_STATUS_QUERY,
      { selector },
    );
    const result = asRecord(data.sensorOrError);
    if (result?.__typename !== "Sensor") {
      throw sensorError("SENSOR_RESULT_ERROR", "query_sensor", result?.__typename);
    }
    if (stringValue(result.name) !== selector.sensorName) {
      throw sensorError("SENSOR_IDENTITY_MISMATCH", "query_sensor");
    }

    const state = asRecord(result.sensorState);
    const status = sensorStatus(state?.status, "query_sensor");
    const defaultStatus = sensorStatus(result.defaultStatus, "query_sensor");
    const canReset = booleanValue(result.canReset, "query_sensor");
    const minIntervalSeconds = nonNegativeInteger(
      result.minIntervalSeconds,
      "query_sensor",
    );
    const sensorId = requiredString(state?.id, "query_sensor");
    const selectorId = requiredString(state?.selectorId, "query_sensor");
    const observedSelector: QueueSensorSelector = {
      repositoryLocationName: requiredString(
        state?.repositoryLocationName,
        "query_sensor",
      ),
      repositoryName: requiredString(state?.repositoryName, "query_sensor"),
      sensorName: selector.sensorName,
    };
    if (!sameSelector(observedSelector, selector)) {
      throw sensorError("SENSOR_SELECTOR_MISMATCH", "query_sensor");
    }
    const startedTicks = asArray(state?.ticks);
    if (
      startedTicks.some(
        (tick) => stringValue(asRecord(tick)?.status) !== "STARTED",
      )
    ) {
      throw sensorError("STARTED_TICK_CONTRACT", "query_sensor");
    }

    return {
      canReset,
      defaultStatus,
      minIntervalSeconds,
      selector: observedSelector,
      selectorId,
      sensorId,
      startedTickCount: startedTicks.length,
      status,
    };
  }

  async #waitForStatus(
    expected: QueueSensorStatus,
    operation: string,
  ): Promise<QueueSensorSnapshot> {
    const deadline = Date.now() + this.#operationTimeoutMs;
    while (Date.now() < deadline) {
      const observed = await this.#observe();
      if (observed.status === expected) return withoutTicks(observed);
      await delay(this.#pollIntervalMs);
    }
    throw sensorError("STATUS_TIMEOUT", operation);
  }

  async #waitForStoppedQuiescence(
    minIntervalSeconds: number,
    operation: string,
  ): Promise<QueueSensorSnapshot> {
    const deadline = Date.now() + this.#operationTimeoutMs;
    const stableForMs =
      minIntervalSeconds * 1_000 + QUIESCENCE_SAFETY_MARGIN_MS;
    let quietSince: number | null = null;
    while (Date.now() < deadline) {
      const observed = await this.#observe();
      if (observed.status === "STOPPED" && observed.startedTickCount === 0) {
        quietSince ??= Date.now();
        if (Date.now() - quietSince >= stableForMs) {
          return withoutTicks(observed);
        }
      } else {
        quietSince = null;
      }
      await delay(this.#pollIntervalMs);
    }
    throw sensorError("QUIESCENCE_TIMEOUT", operation);
  }

  async #mutateOwnedSensor(
    phase: "stopping" | "starting" | "restoring",
    operation: string,
    query: string,
    variables: Record<string, unknown>,
    resultField: string,
    resultTypename: string,
    before: QueueSensorSnapshot,
    intendedAfter: QueueSensorSnapshot,
    waitForIntendedAfter: () => Promise<QueueSensorSnapshot>,
  ): Promise<QueueSensorSnapshot> {
    this.#requireMutationStateFile(operation);
    this.#assertEndpointAttestation(operation);
    this.#mutationIntent = { before, intendedAfter, operation };
    await this.#persist(phase, before);

    let mutationError: unknown = null;
    try {
      const data = await this.#postGraphql(operation, query, variables);
      requireTypename(data, resultField, resultTypename, operation);
    } catch (error) {
      mutationError = error;
    }

    let observed: QueueSensorSnapshot;
    if (mutationError) {
      observed = await this.#settleUncertainMutation(
        before,
        intendedAfter,
        operation,
      ).catch(async () => {
        await this.#persist("restore_failed", before);
        throw sensorError("MUTATION_OUTCOME_UNCERTAIN", operation);
      });
    } else {
      try {
        observed = await waitForIntendedAfter();
      } catch {
        observed = await this.#settleUncertainMutation(
          before,
          intendedAfter,
          operation,
        ).catch(async () => {
          await this.#persist("restore_failed", before);
          throw sensorError("MUTATION_OUTCOME_UNCERTAIN", operation);
        });
        mutationError = sensorError("MUTATION_WAIT_FAILED", operation);
      }
    }

    const isBefore = sameOperationalSnapshot(observed, before);
    const isAfter = sameOperationalSnapshot(observed, intendedAfter);
    if (!isBefore && !isAfter) {
      throw sensorError("CONCURRENT_SENSOR_DRIFT", operation);
    }

    if (mutationError && isBefore) {
      this.#ownedExpectedSnapshot = before;
      await this.#persist("restore_failed", before);
      throw sensorError("MUTATION_OUTCOME_UNCERTAIN", operation);
    }
    if (!isAfter) {
      throw sensorError("MUTATION_NOT_APPLIED", operation);
    }
    this.#ownedExpectedSnapshot = observed;
    this.#mutationIntent = null;
    await this.#persist(phase, observed);
    return observed;
  }

  async #resolveUncertainMutationBeforeRestore(): Promise<void> {
    const intent = this.#mutationIntent;
    if (!intent) return;

    let observed: QueueSensorSnapshot;
    try {
      observed = await this.#settleUncertainMutation(
        intent.before,
        intent.intendedAfter,
        `settle_${intent.operation}`,
      );
    } catch {
      await this.#persist("restore_failed", intent.before);
      throw sensorError("MUTATION_OUTCOME_UNCERTAIN", intent.operation);
    }
    if (sameOperationalSnapshot(observed, intent.before)) {
      this.#ownedExpectedSnapshot = intent.before;
      await this.#persist("restore_failed", intent.before);
      throw sensorError("MUTATION_OUTCOME_UNCERTAIN", intent.operation);
    }

    this.#ownedExpectedSnapshot = observed;
    this.#mutationIntent = null;
    await this.#persist("restoring", observed);
  }

  async #settleUncertainMutation(
    before: QueueSensorSnapshot,
    intendedAfter: QueueSensorSnapshot,
    operation: string,
  ): Promise<QueueSensorSnapshot> {
    const settlementWindowMs = Math.min(
      this.#operationTimeoutMs,
      Math.max(this.#requestTimeoutMs, this.#pollIntervalMs * 3),
    );
    const deadline = Date.now() + settlementWindowMs;
    let lastBefore = before;
    let successfulObservations = 0;

    while (Date.now() < deadline || successfulObservations < 2) {
      const observed = withoutTicks(await this.#observe());
      successfulObservations += 1;
      if (sameOperationalSnapshot(observed, intendedAfter)) return observed;
      if (!sameOperationalSnapshot(observed, before)) {
        throw sensorError("CONCURRENT_SENSOR_DRIFT", operation);
      }
      lastBefore = observed;
      if (Date.now() >= deadline && successfulObservations >= 2) break;
      await delay(this.#pollIntervalMs);
    }
    return lastBefore;
  }

  async #postGraphql(
    operation: string,
    query: string,
    variables: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    if (/^\s*mutation\b/.test(query)) {
      this.#assertEndpointAttestation(operation);
    }
    let response: Response;
    try {
      response = await fetch(this.#graphqlUrl, {
        body: JSON.stringify({ query, variables }),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        method: "POST",
        redirect: "error",
        signal: AbortSignal.timeout(this.#requestTimeoutMs),
      });
    } catch {
      throw sensorError("TRANSPORT_ERROR", operation);
    }
    if (!response.ok) {
      throw sensorError("HTTP_ERROR", operation, undefined, response.status);
    }

    let envelope: GraphqlEnvelope;
    try {
      envelope = (await response.json()) as GraphqlEnvelope;
    } catch {
      throw sensorError("INVALID_JSON", operation);
    }
    if (Array.isArray(envelope.errors) && envelope.errors.length > 0) {
      throw sensorError("GRAPHQL_ERROR", operation);
    }
    const data = asRecord(envelope.data);
    if (!data) throw sensorError("MISSING_DATA", operation);
    return data;
  }

  #requireSelector(): QueueSensorSelector {
    if (!this.#selector) throw sensorError("NOT_INITIALIZED", "controller");
    return this.#selector;
  }

  #assertSameSelector(selector: QueueSensorSelector): void {
    if (!sameSelector(this.#requireSelector(), selector)) {
      throw sensorError("SNAPSHOT_SELECTOR_MISMATCH", "controller");
    }
  }

  #assertEndpointAttestation(operation: string): void {
    const currentExpected = lowercaseSha256(
      process.env.E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256,
      operation,
    );
    if (
      currentExpected !== this.#expectedGraphqlUrlSha256 ||
      currentExpected !== this.#graphqlUrlSha256
    ) {
      throw sensorError("DAGSTER_ORIGIN_ATTESTATION_MISMATCH", operation);
    }
  }

  #assertOwnedExpected(
    observed: SensorObservation,
    operation: string,
  ): void {
    if (
      !this.#ownedExpectedSnapshot ||
      !sameOperationalSnapshot(
        withoutTicks(observed),
        this.#ownedExpectedSnapshot,
      )
    ) {
      throw sensorError("CONCURRENT_SENSOR_DRIFT", operation);
    }
  }

  #requireMutationStateFile(operation: string): string {
    if (!this.#stateFile) {
      throw sensorError("STATE_FILE_REQUIRED", operation);
    }
    return this.#stateFile;
  }

  async #assertStateFileClaimable(): Promise<void> {
    if (!this.#stateFile) return;
    let raw: string;
    try {
      raw = await readFile(this.#stateFile, "utf8");
    } catch (error) {
      if (asNodeError(error).code === "ENOENT") return;
      throw sensorError("STATE_READ_FAILED", "state_file");
    }
    let existing: Record<string, unknown> | null;
    try {
      existing = asRecord(JSON.parse(raw));
    } catch {
      throw sensorError("INVALID_EXISTING_STATE", "state_file");
    }
    if (!existing) {
      throw sensorError("INVALID_EXISTING_STATE", "state_file");
    }
    const phase = stringValue(existing.phase);
    const actualHash = stringValue(existing.dagsterGraphqlEndpointSha256);
    if (actualHash !== this.#graphqlUrlSha256) {
      throw sensorError("EXISTING_STATE_ENDPOINT_MISMATCH", "state_file");
    }
    if (
      phase === "orchestrator_started" &&
      hasExactKeys(existing, [
        "dagsterGraphqlEndpointSha256",
        "phase",
        "version",
      ]) &&
      existing.version === 2
    ) {
      return;
    }
    if (
      phase === "restored" &&
      hasExactKeys(existing, [
        "dagsterGraphqlEndpointSha256",
        "expectedDagsterGraphqlEndpointSha256",
        "initialSensor",
        "mutationIntent",
        "observedSensor",
        "ownedExpectedSensor",
        "phase",
        "updatedAt",
        "version",
      ]) &&
      existing.version === 3 &&
      existing.expectedDagsterGraphqlEndpointSha256 ===
        this.#expectedGraphqlUrlSha256 &&
      existing.mutationIntent === null &&
      isQueueSensorSnapshot(existing.initialSensor) &&
      isQueueSensorSnapshot(existing.observedSensor) &&
      isQueueSensorSnapshot(existing.ownedExpectedSensor) &&
      typeof existing.updatedAt === "string" &&
      existing.updatedAt.length > 0 &&
      sameUnknownSnapshot(existing.initialSensor, existing.observedSensor) &&
      sameUnknownSnapshot(existing.initialSensor, existing.ownedExpectedSensor)
    ) {
      return;
    }
    throw sensorError("UNRESTORED_EXISTING_STATE", "state_file");
  }

  async #persist(
    phase: PersistedSensorState["phase"],
    sensor: QueueSensorSnapshot,
  ): Promise<void> {
    if (!this.#stateFile) return;
    const state: PersistedSensorState = {
      dagsterGraphqlEndpointSha256: this.#graphqlUrlSha256,
      expectedDagsterGraphqlEndpointSha256: this.#expectedGraphqlUrlSha256,
      initialSensor: this.#initialSnapshot ?? sensor,
      mutationIntent: this.#mutationIntent,
      observedSensor: sensor,
      ownedExpectedSensor: this.#ownedExpectedSnapshot ?? sensor,
      phase,
      updatedAt: new Date().toISOString(),
      version: 3,
    };
    const directory = path.dirname(this.#stateFile);
    const temporary = `${this.#stateFile}.${process.pid}.${randomUUID()}.tmp`;
    try {
      await mkdir(directory, { mode: 0o700, recursive: true });
      await writeFile(temporary, `${JSON.stringify(state)}\n`, {
        encoding: "utf8",
        flag: "wx",
        mode: 0o600,
      });
      await chmod(temporary, 0o600);
      const temporaryHandle = await open(temporary, "r");
      try {
        await temporaryHandle.sync();
      } finally {
        await temporaryHandle.close();
      }
      await rename(temporary, this.#stateFile);
      await chmod(this.#stateFile, 0o600);
      const stateHandle = await open(this.#stateFile, "r");
      try {
        await stateHandle.sync();
      } finally {
        await stateHandle.close();
      }
      const directoryHandle = await open(directory, "r");
      try {
        await directoryHandle.sync();
      } finally {
        await directoryHandle.close();
      }
    } catch {
      await rm(temporary, { force: true }).catch(() => undefined);
      throw sensorError("STATE_WRITE_FAILED", "state_file");
    }
  }
}

export async function createQueueSensorController(
  options: QueueSensorControllerOptions = {},
): Promise<QueueSensorController> {
  const controller = new QueueSensorController(options);
  await controller.initialize();
  return controller;
}

export async function snapshotQueueSensor(
  controller: QueueSensorController,
): Promise<QueueSensorSnapshot> {
  return controller.captureSnapshot();
}

export async function stopQueueSensorAndWaitForQuiescence(
  controller: QueueSensorController,
  initial: QueueSensorSnapshot,
): Promise<QueueSensorSnapshot> {
  return controller.stopAndWaitForQuiescence(initial);
}

export async function startQueueSensor(
  controller: QueueSensorController,
): Promise<QueueSensorSnapshot> {
  return controller.start();
}

export async function restoreQueueSensor(
  controller: QueueSensorController,
  initial: QueueSensorSnapshot,
): Promise<QueueSensorSnapshot> {
  return controller.restore(initial);
}

export class C7DagsterSensorError extends Error {
  readonly code: string;
  readonly operation: string;

  constructor(
    code: string,
    operation: string,
    typename?: string,
    httpStatus?: number,
  ) {
    const safeContext = [
      `code=${code}`,
      `operation=${operation}`,
      ...(typename ? [`typename=${typename}`] : []),
      ...(httpStatus === undefined ? [] : [`http_status=${httpStatus}`]),
    ].join(", ");
    super(`C7 Dagster sensor operation failed (${safeContext}; values redacted)`);
    this.name = "C7DagsterSensorError";
    this.code = code;
    this.operation = operation;
  }
}

function graphqlEndpoint(rawValue: string | undefined): URL {
  if (!rawValue) throw sensorError("MISSING_DAGSTER_URL", "configuration");
  let url: URL;
  try {
    url = new URL(rawValue);
  } catch {
    throw sensorError("INVALID_DAGSTER_URL", "configuration");
  }
  if (
    url.protocol !== "https:" ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    throw sensorError("UNSAFE_DAGSTER_URL", "configuration");
  }
  const pathname = url.pathname.replace(/\/+$/, "");
  url.pathname = pathname.endsWith("/graphql")
    ? pathname
    : `${pathname}/graphql`;
  return url;
}

function stateFilePath(rawValue: string | undefined): string | null {
  if (!rawValue) return null;
  if (!path.isAbsolute(rawValue)) {
    throw sensorError("STATE_FILE_NOT_ABSOLUTE", "configuration");
  }
  return rawValue;
}

function requireTypename(
  data: Record<string, unknown>,
  field: string,
  expected: string,
  operation: string,
): void {
  const typename = stringValue(asRecord(data[field])?.__typename);
  if (typename !== expected) {
    throw sensorError("MUTATION_RESULT_ERROR", operation, typename);
  }
}

function withoutTicks(observation: SensorObservation): QueueSensorSnapshot {
  const snapshot = { ...observation };
  Reflect.deleteProperty(snapshot, "startedTickCount");
  return snapshot;
}

function sameSelector(
  left: QueueSensorSelector,
  right: QueueSensorSelector,
): boolean {
  return (
    left.repositoryLocationName === right.repositoryLocationName &&
    left.repositoryName === right.repositoryName &&
    left.sensorName === right.sensorName
  );
}

function sameOperationalSnapshot(
  left: QueueSensorSnapshot,
  right: QueueSensorSnapshot,
): boolean {
  // canReset은 dagster가 파생하는 "status override 존재" 힌트일 뿐 sensor의
  // 운영 상태(RUNNING/STOPPED)가 아니다. defaultStatus=RUNNING sensor를 start하면
  // status는 즉시 RUNNING이 되지만 canReset은 (override 기록 때문에) true로 남거나
  // false로 지연 수렴한다. canReset을 operational 비교에 넣으면 start 직후 관측된
  // {RUNNING, canReset:true}가 intendedAfter {RUNNING, canReset:false}와도, before
  // {STOPPED}와도 불일치해 허위 CONCURRENT_SENSOR_DRIFT가 난다(empty-write의 sensor
  // quiescence dance가 preview 통과 후 처음 도달해 노출). restore 분기는 canReset을
  // 직접 필드로 읽어 판단하므로, operational 비교에서는 canReset을 제외한다.
  return (
    left.defaultStatus === right.defaultStatus &&
    left.minIntervalSeconds === right.minIntervalSeconds &&
    left.selectorId === right.selectorId &&
    left.sensorId === right.sensorId &&
    left.status === right.status &&
    sameSelector(left.selector, right.selector)
  );
}

function withSensorStatus(
  snapshot: QueueSensorSnapshot,
  status: QueueSensorStatus,
): QueueSensorSnapshot {
  return {
    ...snapshot,
    canReset: status !== snapshot.defaultStatus,
    status,
  };
}

function sameUnknownSnapshot(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expectedKeys: string[],
): boolean {
  const actual = Object.keys(value).sort();
  return JSON.stringify(actual) === JSON.stringify([...expectedKeys].sort());
}

function isQueueSensorSnapshot(value: unknown): value is QueueSensorSnapshot {
  const snapshot = asRecord(value);
  if (
    !snapshot ||
    !hasExactKeys(snapshot, [
      "canReset",
      "defaultStatus",
      "minIntervalSeconds",
      "selector",
      "selectorId",
      "sensorId",
      "status",
    ])
  ) {
    return false;
  }
  const selector = asRecord(snapshot.selector);
  return (
    typeof snapshot.canReset === "boolean" &&
    (snapshot.defaultStatus === "RUNNING" ||
      snapshot.defaultStatus === "STOPPED") &&
    typeof snapshot.minIntervalSeconds === "number" &&
    Number.isInteger(snapshot.minIntervalSeconds) &&
    snapshot.minIntervalSeconds >= 0 &&
    typeof snapshot.selectorId === "string" &&
    snapshot.selectorId.length > 0 &&
    typeof snapshot.sensorId === "string" &&
    snapshot.sensorId.length > 0 &&
    (snapshot.status === "RUNNING" || snapshot.status === "STOPPED") &&
    selector !== null &&
    hasExactKeys(selector, [
      "repositoryLocationName",
      "repositoryName",
      "sensorName",
    ]) &&
    typeof selector.repositoryLocationName === "string" &&
    selector.repositoryLocationName.length > 0 &&
    typeof selector.repositoryName === "string" &&
    selector.repositoryName.length > 0 &&
    typeof selector.sensorName === "string" &&
    selector.sensorName.length > 0
  );
}

function asNodeError(error: unknown): { code?: string } {
  return typeof error === "object" && error !== null
    ? (error as { code?: string })
    : {};
}

function sensorStatus(value: unknown, operation: string): QueueSensorStatus {
  if (value === "RUNNING" || value === "STOPPED") return value;
  throw sensorError("INVALID_SENSOR_STATUS", operation);
}

function booleanValue(value: unknown, operation: string): boolean {
  if (typeof value === "boolean") return value;
  throw sensorError("INVALID_BOOLEAN", operation);
}

function nonNegativeInteger(value: unknown, operation: string): number {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) {
    return value;
  }
  throw sensorError("INVALID_INTEGER", operation);
}

function positiveInteger(value: number, field: string): number {
  if (Number.isInteger(value) && value > 0) return value;
  throw sensorError("INVALID_OPTION", field);
}

function lowercaseSha256(
  value: string | undefined,
  operation: string,
): string {
  if (!value || !/^[0-9a-f]{64}$/.test(value)) {
    throw sensorError("INVALID_DAGSTER_ORIGIN_SHA256", operation);
  }
  return value;
}

function requiredString(value: unknown, operation: string): string {
  const parsed = stringValue(value);
  if (parsed) return parsed;
  throw sensorError("INVALID_STRING", operation);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function sensorError(
  code: string,
  operation: string,
  typename?: unknown,
  httpStatus?: number,
): C7DagsterSensorError {
  return new C7DagsterSensorError(
    code,
    operation,
    typeof typename === "string" ? typename : undefined,
    httpStatus,
  );
}
