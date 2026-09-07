"use client";

/**
 * T-VN-M05 수동/provider 중복 판정 화면.
 *
 * **generic dedup 화면을 재사용하지 않는다**(인수조건 M05-5). 그 화면은 provider
 * 사이의 중복을 다루고 판정이 되돌릴 수 있다. 여기는 다르다:
 *
 * - `merged`·`manual_retired`는 **수동 Feature를 되돌릴 수 없게** 바꾼다.
 * - survivor는 **항상 provider Feature**다 — 고를 수 있게 두면 안 된다.
 * - 판정 결과가 외부 consumer에게 전파되므로 **누가 얼마나 밀려 있는지**를 보고
 *   결정해야 한다.
 *
 * 그래서 기본값은 `kept`이고, 파괴적 판정은 확인 문구를 따로 받는다.
 */

import { useEffect, useMemo, useState } from "react";

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

export function ManualProviderDedupClient() {
  const [status, setStatus] = useState<ManualProviderDedupStatus>("pending");
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const cases = useManualProviderDedupCases({ status });

  const items = cases.data?.data.items ?? [];

  return (
    <div className="mpd-layout">
      <header>
        <h1>수동/provider 중복 판정</h1>
        <p>
          탐지기가 올린 후보를 admin이 판정한다. <strong>자동으로 병합되지
          않는다</strong> — 이 화면의 판정만이 상태를 바꾼다.
        </p>
        <label>
          상태
          <select
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as ManualProviderDedupStatus)
            }
          >
            <option value="pending">미해결</option>
            <option value="terminal">판정 완료</option>
          </select>
        </label>
      </header>

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

      {selectedCaseId ? (
        <CaseDecisionPanel
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

  // `Date.now()`를 렌더 중에 부르면 불순 호출이고, 한 번 고정하면 밀린 시간이
  // 화면에 남아 있는 동안 낡는다. effect에서 재고, 1분마다 갱신한다.
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);

  const data = detail.data?.data;
  const subscriptions = useMemo(() => data?.subscriptions ?? [], [data]);
  const unacked = useMemo(
    () => (now === null ? [] : unackedAges(subscriptions, now)),
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

  // survivor는 **provider로 고정**이다. 고를 수 있게 두면 수동본을 남기는
  // 조합이 생기는데, 그것은 이 판정의 의미가 아니다.
  const survivorFeatureId = readFeatureId(data.provider_feature);

  return (
    <section aria-label="판정">
      <h2>판정</h2>

      <dl>
        <dt>수동 Feature</dt>
        <dd>{readFeatureId(data.manual_feature)}</dd>
        <dt>provider Feature (survivor 고정)</dt>
        <dd>{survivorFeatureId}</dd>
        <dt>evidence 지문</dt>
        <dd>
          <code>{data.evidence_fingerprint}</code>
        </dd>
      </dl>

      <section aria-label="미확인 consumer">
        <h3>미확인 consumer</h3>
        {now === null ? (
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
            submit.mutate(
              {
                decision,
                reason: trimmedReason,
                expected_case_fingerprint: data.evidence_fingerprint,
                expected_manual_row_revision: readRowRevision(
                  data.manual_feature,
                ),
                expected_provider_row_revision: readRowRevision(
                  data.provider_feature,
                ),
                survivor_feature_id: destructive ? survivorFeatureId : null,
              },
              { onSuccess: onResolved },
            );
          }}
        >
          판정 제출
        </button>
      </fieldset>

      {alreadyResolved ? <p>이미 판정된 후보다.</p> : null}
      {submit.isError ? (
        <p role="alert">판정을 제출하지 못했다. 후보가 그 사이 바뀌었을 수 있다.</p>
      ) : null}
    </section>
  );
}

/**
 * detail 응답의 feature 블록은 스키마상 자유 object다(`additionalProperties`).
 * 계약이 좁혀 주지 않으므로 여기서 좁히되, **없으면 지어내지 않고 드러낸다** —
 * 빈 문자열이면 제출 버튼이 서버 검증에 걸려 실패하는 편이 조용히 잘못된 값을
 * 보내는 것보다 낫다.
 */
function readFeatureId(feature: Record<string, unknown>): string {
  const value = feature["feature_id"];
  return typeof value === "string" ? value : "";
}

function readRowRevision(feature: Record<string, unknown>): number {
  const value = feature["row_revision"];
  return typeof value === "number" ? value : 0;
}
