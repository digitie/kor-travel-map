"use client";

/**
 * T-VN-M05 수동/provider 중복 판정 화면.
 *
 * **generic dedup 화면을 재사용하지 않는다**(인수조건 M05-5). 그 화면은 provider
 * 사이의 중복을 다루고 판정이 되돌릴 수 있다. 여기는 다르다:
 *
 * - `merged`·`manual_retired`는 **수동 Feature를 되돌릴 수 없게** 바꾼다.
 * - survivor는 **`merged` 전용 개념**이다 — `manual_retired`는 수동본만 폐기하고
 *   survivor를 받지 않는다(계약이 교차필드로 막는다).
 * - 판정 결과가 외부 consumer에게 전파되므로 **누가 얼마나 밀려 있는지**를 보고
 *   결정해야 한다.
 */

import { useMemo, useState, useSyncExternalStore } from "react";

import {
  formatUnackedAge,
  isDestructiveDecision,
  unackedAges,
  useManualProviderDedupCase,
  useManualProviderDedupCases,
  useSubmitManualProviderDedupDecision,
  type ManualProviderDedupCase,
  type ManualProviderDedupDecision,
  type ManualProviderDedupStatus,
} from "@/api/manualProviderDedup";

const DECISION_LABELS: Record<ManualProviderDedupDecision, string> = {
  kept: "유지 — 중복이 아니다",
  merged: "병합 — provider가 남고 수동본은 흡수된다",
  manual_retired: "수동본 폐기 — provider가 남는다",
};

/** 파괴적 판정을 실행하려면 이 문구를 그대로 입력해야 한다. */
const DESTRUCTIVE_CONFIRMATION = "폐기를 확인합니다";

const MINUTE_MS = 60_000;

/**
 * 분 단위로 흐르는 시계.
 *
 * `Date.now()`를 렌더 중에 부르면 불순 호출이고, effect에서 state로 넣는 것도
 * 금지돼 있다(`react-hooks/set-state-in-effect`). 값을 분 경계로 양자화해 snapshot을
 * 안정시키고, **subscribe를 모듈 수준 상수로 둬** 매 렌더 재구독되지 않게 한다 —
 * 인라인 함수면 렌더마다 새 구독이 되어 타이머가 리셋된다(적대 리뷰가 잡았다).
 * SSR snapshot은 `0`이고, 호출부는 그것을 "아직 모른다"로 읽는다.
 */
function subscribeToMinute(onStoreChange: () => void): () => void {
  const timer = setInterval(onStoreChange, MINUTE_MS);
  return () => clearInterval(timer);
}

function minuteSnapshot(): number {
  return Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS;
}

function serverMinuteSnapshot(): number {
  return 0;
}

function useMinuteClock(): number {
  return useSyncExternalStore(
    subscribeToMinute,
    minuteSnapshot,
    serverMinuteSnapshot,
  );
}

export function ManualProviderDedupClient() {
  const [status, setStatus] = useState<ManualProviderDedupStatus>("pending");
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  // 커서 이력. 계약이 `next_after_*` 둘을 주는데 쓰지 않으면 51번째 case부터
  // 화면에 존재하지 않는다(기본 limit 50).
  const [cursors, setCursors] = useState<
    Array<{ after_created_at: string | null; after_case_id: string | null }>
  >([{ after_created_at: null, after_case_id: null }]);
  const cursor = cursors[cursors.length - 1];
  const cases = useManualProviderDedupCases({ status, ...cursor });

  const page = cases.data?.data;
  const items = page?.items ?? [];
  const hasNext = Boolean(page?.next_after_case_id);

  const resetPaging = () => {
    setCursors([{ after_created_at: null, after_case_id: null }]);
    setSelectedCaseId(null);
  };

  // `AdminShell`은 **page**가 두른다. 여기서 두르면 `usePathname`이 붙어 이 화면의
  // 안전장치를 재는 컴포넌트 테스트가 라우터 없이는 돌지 않는다 — 셸은 라우트의
  // 관심사이고, 이 컴포넌트의 관심사는 "무엇을 막는가"다.
  return (
    <div>
        <label>
          상태
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as ManualProviderDedupStatus);
              resetPaging();
            }}
          >
            <option value="pending">미해결</option>
            <option value="terminal">판정 완료</option>
          </select>
        </label>

        {cases.isPending ? <p>불러오는 중…</p> : null}
        {cases.isError ? <p role="alert">목록을 불러오지 못했다.</p> : null}
        {!cases.isPending && items.length === 0 ? (
          <p>이 상태의 후보가 없다.</p>
        ) : null}

        <ul aria-label="중복 후보">
          {items.map((item) => (
            <li key={item.case_id}>
              <button
                type="button"
                aria-pressed={selectedCaseId === item.case_id}
                onClick={() => setSelectedCaseId(item.case_id)}
              >
                <CaseSummary item={item} />
              </button>
            </li>
          ))}
        </ul>

        <nav aria-label="페이지">
          <button
            type="button"
            disabled={cursors.length <= 1}
            onClick={() => {
              setCursors((previous) => previous.slice(0, -1));
              setSelectedCaseId(null);
            }}
          >
            이전
          </button>
          <button
            type="button"
            disabled={!hasNext}
            onClick={() => {
              setCursors((previous) => [
                ...previous,
                {
                  after_created_at: page?.next_after_created_at ?? null,
                  after_case_id: page?.next_after_case_id ?? null,
                },
              ]);
              setSelectedCaseId(null);
            }}
          >
            다음
          </button>
        </nav>

        {selectedCaseId ? (
          // **`key`로 remount한다.** 없으면 case를 바꿔도 decision·reason·확인 문구와
          // mutation 상태가 남아, 앞 case에서 입력한 확인 문구로 다음 case의 파괴적
          // 판정이 무장된다 — M05-5의 안전장치 셋이 두 번째 case부터 전부 무력화된다
          // (적대 리뷰 BLOCKER).
          <CaseDecisionPanel
            key={selectedCaseId}
            caseId={selectedCaseId}
            onResolved={() => setSelectedCaseId(null)}
          />
      ) : null}
    </div>
  );
}

function CaseSummary({ item }: { item: ManualProviderDedupCase }) {
  return (
    <span>
      <strong>{item.manual_feature.feature_id}</strong>
      {" ↔ "}
      <strong>{item.provider_feature.feature_id}</strong>
      {" · 총점 "}
      {item.scores.total_score.toFixed(3)}
      {" · "}
      {item.scores.distance_meters.toFixed(1)}m
    </span>
  );
}

function CaseDecisionPanel({
  caseId,
  onResolved,
}: {
  caseId: string;
  onResolved: () => void;
}) {
  const detail = useManualProviderDedupCase(caseId);
  const submit = useSubmitManualProviderDedupDecision(caseId);

  // **기본값은 항상 `kept`다.** 파괴적 판정을 기본으로 두면 실수 한 번이 되돌릴
  // 수 없는 변경이 된다(M05-5).
  const [decision, setDecision] = useState<ManualProviderDedupDecision>("kept");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const now = useMinuteClock();
  const data = detail.data?.data;
  const subscriptions = useMemo(() => data?.subscriptions ?? [], [data]);
  const unacked = useMemo(
    () => (now === 0 ? [] : unackedAges(subscriptions, now)),
    [subscriptions, now],
  );

  if (detail.isPending) {
    return <p>후보를 불러오는 중…</p>;
  }
  if (detail.isError || !data) {
    return <p role="alert">후보를 불러오지 못했다.</p>;
  }

  const destructive = isDestructiveDecision(decision);
  const trimmedReason = reason.trim();
  const reasonMissing = trimmedReason.length === 0;
  const confirmationMissing =
    destructive && confirmation.trim() !== DESTRUCTIVE_CONFIRMATION;
  const alreadyResolved = data.status === "terminal";
  const blocked = reasonMissing || confirmationMissing || alreadyResolved;

  // survivor는 provider로 고정이되 **`merged`에만 실린다.** 계약이 교차필드로
  // `decision != 'merged' AND survivor IS NOT NULL`을 막으므로(라우터 validator와
  // DB `ck_m05_decision_input`), `manual_retired`에 실으면 서버가 100% 422를 낸다.
  // OpenAPI에는 이 규칙이 표현되지 않아 tsc가 잡지 못한다 — 컴파일 통과가 안전을
  // 뜻하지 않는 자리다(적대 리뷰 BLOCKER).
  const survivorFeatureId = readFeatureId(data.provider_feature);
  const survivorForDecision = decision === "merged" ? survivorFeatureId : null;

  const resolved = submit.data?.data;

  return (
    <section aria-label="판정">
      <h2>판정</h2>

      <dl>
        <dt>수동 Feature</dt>
        <dd>{readFeatureId(data.manual_feature)}</dd>
        <dt>provider Feature (병합 시 survivor)</dt>
        <dd>{survivorFeatureId}</dd>
        <dt>evidence 지문</dt>
        <dd>
          <code>{data.evidence_fingerprint}</code>
        </dd>
      </dl>

      <section aria-label="미확인 consumer">
        <h3>미확인 consumer</h3>
        <p>
          이 case가 아니라 <strong>그 principal의 구독 전체</strong>가 밀린 시간이다 —
          판정 결과가 전파되기까지 얼마나 걸릴지의 지표다.
        </p>
        {now === 0 ? (
          <p>계산 중…</p>
        ) : unacked.length === 0 ? (
          <p>밀린 consumer가 없다.</p>
        ) : (
          <ul>
            {unacked.map((entry) => (
              <li key={entry.principalId}>
                {entry.principalId} — {formatUnackedAge(entry.ageMs)} 밀림
              </li>
            ))}
          </ul>
        )}
      </section>

      <fieldset disabled={alreadyResolved}>
        <legend>결정</legend>
        {(
          Object.keys(DECISION_LABELS) as ManualProviderDedupDecision[]
        ).map((value) => (
          <label key={value}>
            <input
              type="radio"
              name="decision"
              value={value}
              checked={decision === value}
              onChange={() => {
                setDecision(value);
                setConfirmation("");
              }}
            />
            {DECISION_LABELS[value]}
          </label>
        ))}

        <label>
          사유 (필수)
          <textarea
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        {reasonMissing ? <p role="alert">사유를 입력해야 한다.</p> : null}

        {destructive ? (
          <label>
            이 판정은 <strong>되돌릴 수 없다.</strong> 실행하려면{" "}
            <code>{DESTRUCTIVE_CONFIRMATION}</code>를 그대로 입력한다.
            <input
              type="text"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </label>
        ) : null}

        <button
          type="button"
          disabled={blocked || submit.isPending}
          onClick={() => {
            submit.mutate({
              decision,
              reason: trimmedReason,
              expected_case_fingerprint: data.evidence_fingerprint,
              expected_manual_row_revision: readRowRevision(data.manual_feature),
              expected_provider_row_revision: readRowRevision(
                data.provider_feature,
              ),
              survivor_feature_id: survivorForDecision,
            });
          }}
        >
          판정 제출
        </button>
      </fieldset>

      {alreadyResolved ? <p>이미 판정된 후보다.</p> : null}
      {submit.isError ? (
        <p role="alert">{submitFailureMessage(submit.error)}</p>
      ) : null}
      {resolved ? (
        // 판정이 무엇을 만들었는지 보여 준다 — 받아 놓고 버리면 사용자는 그 판정이
        // 실제로 반영됐는지 확인할 방법이 없다(적대 리뷰 MAJOR).
        <section aria-label="판정 결과">
          <h3>판정 결과</h3>
          <dl>
            <dt>결과</dt>
            <dd>{resolved.outcome}</dd>
            <dt>resolution</dt>
            <dd>
              <code>{resolved.resolution_id}</code>
            </dd>
            <dt>전파 event</dt>
            <dd>
              {resolved.event_id ? (
                <code>{resolved.event_id}</code>
              ) : (
                "없음 (전파 대상 없음)"
              )}
            </dd>
          </dl>
          <button type="button" onClick={onResolved}>
            목록으로
          </button>
        </section>
      ) : null}
    </section>
  );
}

/**
 * 실패 사유를 구별해 보여 준다.
 *
 * 전부 한 문장으로 뭉개면 운영자가 **무엇을 해야 하는지** 알 수 없다 — 409는 다시
 * 읽어야 하고, 403은 권한 문제이며, 422는 요청이 계약을 어긴 것이고, 503은 잠시 뒤
 * 재시도다. 로컬 멱등 fingerprint 불일치는 서버에 닿지도 않은 것이라 또 다르다.
 */
function submitFailureMessage(error: unknown): string {
  const status = readStatus(error);
  if (status === 409) {
    return "후보가 그 사이 바뀌었다. 목록에서 다시 열어 최신 증거로 판정한다.";
  }
  if (status === 403) {
    return "이 판정을 실행할 권한이 없다.";
  }
  if (status === 422) {
    return "요청이 계약을 어겼다. 화면 버그일 수 있으니 그대로 보고한다.";
  }
  if (status === 503) {
    return "판정 경로가 일시적으로 닫혀 있다. 잠시 뒤 다시 시도한다.";
  }
  if (error instanceof Error && error.name.includes("Idempotency")) {
    return "같은 case에 대해 이미 다른 내용으로 제출을 시작했다. 목록에서 다시 열어야 한다.";
  }
  return "판정을 제출하지 못했다.";
}

function readStatus(error: unknown): number | null {
  if (typeof error !== "object" || error === null) {
    return null;
  }
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" ? status : null;
}

/**
 * detail 응답의 feature 블록은 스키마상 자유 object다(`additionalProperties`).
 * 계약이 좁혀 주지 않으므로 여기서 좁히되, **없으면 지어내지 않고 드러낸다** —
 * 빈 문자열이면 제출이 서버 검증에 걸려 실패하는 편이 조용히 잘못된 값을 보내는
 * 것보다 낫다.
 */
function readFeatureId(feature: Record<string, unknown>): string {
  const value = feature["feature_id"];
  return typeof value === "string" ? value : "";
}

function readRowRevision(feature: Record<string, unknown>): number {
  const value = feature["row_revision"];
  return typeof value === "number" ? value : 0;
}
