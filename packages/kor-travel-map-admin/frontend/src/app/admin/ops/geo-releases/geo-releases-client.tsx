"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { RadarIcon, RefreshCwIcon, RotateCcwIcon, XIcon } from "lucide-react";
import { useMemo, useState } from "react";

import {
  type GeoCoverageRecord,
  type GeoReleaseDetectResponse,
  type GeoReleaseItemRecord,
  type GeoReleaseListResponse,
  type GeoReleasePlanRecord,
  canReplan,
  canSkip,
  coverageRatio,
  launchNote,
  notCalledTotal,
  useDetectGeoReleaseMutation,
  useGeoRelease,
  useGeoReleases,
  useReplanGeoReleaseMutation,
  useSkipGeoReleaseItemMutation,
} from "@/api/geoReleases";
import { AdminShell } from "@/components/admin-shell";
import { useConfirm } from "@/components/confirm-dialog";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { SectionCard } from "@/components/section-card";
import { StatStrip } from "@/components/stat-strip";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import { hrefFor } from "@/lib/entity-href";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { statusLabel } from "@/lib/status-label";

/** 센서 Skip 사유와 같은 문장(`dagster/geo_release_sensor.py`) — 운영자가 같은 말을 본다. */
const MISSING_FINGERPRINT_TEXT = "geo data_token 없음 — 지문 backfill/복구 필요";
const UNAVAILABLE_REASON = "kor-travel-geo가 현재 데이터셋을 답하지 않았다 — 감지할 수 없다";

const DETECT_OUTCOME_TEXT: Record<GeoReleaseDetectResponse["data"]["outcome"], string> = {
  no_token: "geo가 data_token을 내지 않았다 — 계획을 만들 수 없다.",
  baseline_recorded: "처음 관측한 토큰을 기준선으로 기록했다(계획 없음).",
  baseline: "이미 기준선인 토큰이다(계획 없음).",
  existing: "같은 토큰의 활성 계획이 이미 있다.",
  created: "새 계획을 만들었다.",
  already_complete: "이 토큰의 계획은 이미 끝났다(재계획 없음).",
};

const REASON_TEXT: Record<string, string> = {
  disabled: "자동 적재 꺼짐",
  no_geo_dependency: "geo 미사용",
  queue_only: "큐 전용(Dagster job 없음)",
  operator: "운영자 건너뜀",
  sweep: "sweep",
  run_not_launched: "run 미기동",
  no_progress: "진척 없음",
  run_failed: "run 실패",
  superseded: "대체된 계획",
  canceled: "run 취소",
};

function planStatus(state: GeoReleasePlanRecord["state"]) {
  return state === "baseline" ? (
    <StatusBadge label="기준선" status={state} tone="neutral" />
  ) : (
    <StatusBadge status={state} />
  );
}

function itemStatus(state: GeoReleaseItemRecord["state"]) {
  return state === "requested" ? (
    <StatusBadge label="요청됨" status={state} tone="info" />
  ) : (
    <StatusBadge status={state} />
  );
}

function CurrentDatasetCard({ data }: { data: GeoReleaseListResponse["data"] | undefined }) {
  if (!data) {
    return null;
  }
  const { current, current_status: status } = data;
  const items: DetailItem[] = [
    { label: "version_token", value: current?.version_token ?? null, mono: true, copyable: true },
    { label: "data_token", value: current?.data_token ?? null, mono: true, copyable: true },
    {
      label: "활성화",
      value: current?.activated_at ? formatDateTime(current.activated_at) : null,
      numeric: true,
    },
    {
      label: "기준 월",
      value: current?.reference_months
        ? Object.entries(current.reference_months)
            .map(([key, value]) => `${key} ${value}`)
            .join(" · ")
        : null,
    },
  ];
  return (
    <SectionCard
      actions={
        status === "ok" ? (
          <Badge variant="success">정상</Badge>
        ) : status === "no_token" ? (
          <Badge variant="destructive">data_token 없음</Badge>
        ) : (
          <Badge variant="warning">응답 없음</Badge>
        )
      }
      description="kor-travel-geo가 지금 서빙하는 데이터셋 — 토큰이 바뀌면 센서가 계획을 만든다."
      title="현재 geo 데이터셋"
    >
      {status === "no_token" ? (
        <Alert variant="destructive">
          <AlertTitle>계획을 만들 수 없음</AlertTitle>
          <AlertDescription>
            <p data-testid="geo-release-skip-reason">센서 Skip 사유: {MISSING_FINGERPRINT_TEXT}</p>
          </AlertDescription>
        </Alert>
      ) : null}
      {status === "unavailable" ? (
        <Alert variant="warning">
          <AlertTitle>geo 응답 없음</AlertTitle>
          <AlertDescription>
            <p data-testid="geo-release-skip-reason">{UNAVAILABLE_REASON}</p>
          </AlertDescription>
        </Alert>
      ) : null}
      <DetailList items={items} layout="inline" />
    </SectionCard>
  );
}

function CoverageGauge({ coverage }: { coverage: GeoCoverageRecord }) {
  const ratio = coverageRatio(coverage);
  const percent = ratio === null ? null : Math.round(ratio * 1000) / 10;
  const notCalled = notCalledTotal(coverage);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-baseline justify-between gap-2 text-xs text-text-secondary">
          <span>현재 토큰 스탬프</span>
          <span className="font-mono tabular-nums text-text-primary" data-testid="geo-coverage-ratio">
            {formatCount(coverage.stamped_current)} / {formatCount(coverage.total_provider_with_coord)}
            {percent === null ? "" : ` (${percent}%)`}
          </span>
        </div>
        <meter
          aria-label="현재 토큰 커버리지"
          className="sr-only"
          max={100}
          min={0}
          value={percent ?? 0}
        >
          {percent === null ? "분모 없음" : `${percent}%`}
        </meter>
        <div aria-hidden="true" className="h-2 w-full overflow-hidden rounded-full bg-surface-muted">
          <div
            className="h-full rounded-full bg-success"
            style={{ width: `${percent ?? 0}%` }}
          />
        </div>
      </div>
      <StatStrip
        ariaLabel="커버리지 상세"
        items={[
          {
            label: "다른 토큰",
            value: coverage.stamped_other,
            tone: coverage.stamped_other > 0 ? "warning" : undefined,
            testId: "geo-coverage-stamped-other",
            help: "옛 토큰으로 해석된 행 — stale이라 다시 적재한다.",
          },
          {
            label: "스탬프 없음",
            value: coverage.unstamped,
            tone: coverage.unstamped > 0 ? "warning" : undefined,
            testId: "geo-coverage-unstamped",
          },
          {
            label: "geo 미호출",
            value: notCalled,
            testId: "geo-coverage-not-called",
            caption:
              Object.entries(coverage.not_called_by_kind)
                .map(([kind, count]) => `${kind} ${formatCount(count)}`)
                .join(" · ") || undefined,
            help: "provider 코드만 쓴 행(not_called) — 토큰 비교 대상이 아니다.",
          },
          {
            label: "skip 제외",
            value: coverage.excluded_by_skip,
            testId: "geo-coverage-excluded",
          },
          {
            label: "provider 밖",
            value: coverage.unstamped_non_provider,
            testId: "geo-coverage-non-provider",
            help: "provider 기원이 아닌 Feature의 스탬프 없음 — 표시만 한다.",
          },
        ]}
      />
    </div>
  );
}

function useItemColumns(
  plan: GeoReleasePlanRecord,
  onSkip: (item: GeoReleaseItemRecord) => void,
  skipping: number | null,
): ColumnDef<GeoReleaseItemRecord, unknown>[] {
  return useMemo<ColumnDef<GeoReleaseItemRecord, unknown>[]>(
    () => [
      {
        accessorKey: "position",
        header: "#",
        meta: { align: "right" } satisfies DataTableColumnMeta,
      },
      {
        accessorKey: "operation_key",
        header: "operation",
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const note = launchNote(row.original);
          return (
            <div className="flex min-w-0 flex-col gap-1">
              <span className="font-mono text-xs break-all">{row.original.operation_key}</span>
              <span className="text-2xs text-text-secondary">
                {row.original.datasets.map((dataset) => dataset.dataset_key).join(", ")}
              </span>
              {note ? (
                <Badge
                  className="w-fit"
                  title={note.detail}
                  variant={note.tone}
                >
                  {note.label}
                </Badge>
              ) : null}
            </div>
          );
        },
      },
      {
        accessorKey: "state",
        header: "상태",
        cell: ({ row }) => (
          <div className="flex flex-col gap-1">
            {itemStatus(row.original.state)}
            {row.original.state_reason ? (
              <span className="text-2xs text-text-secondary">
                {REASON_TEXT[row.original.state_reason] ?? statusLabel(row.original.state_reason)}
              </span>
            ) : null}
          </div>
        ),
      },
      {
        accessorKey: "attempt_seq",
        header: "시도",
        meta: { align: "right" } satisfies DataTableColumnMeta,
      },
      {
        id: "run",
        header: "run",
        cell: ({ row }) => {
          const runId = row.original.dagster_run_id;
          const href = runId ? hrefFor("dagsterRun", runId) : null;
          return href && runId ? (
            <a
              className="font-mono text-xs underline-offset-4 hover:underline"
              href={href}
              rel="noreferrer"
              target="_blank"
              onClick={(event) => event.stopPropagation()}
            >
              {shortId(runId, 8)}
            </a>
          ) : (
            <span className="text-text-tertiary">{NULL_GLYPH}</span>
          );
        },
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) =>
          canSkip(plan, row.original) ? (
            <Button
              aria-label={`항목 ${row.original.position} 건너뛰기`}
              loading={skipping === row.original.position}
              size="sm"
              type="button"
              variant="outline"
              onClick={(event) => {
                event.stopPropagation();
                onSkip(row.original);
              }}
            >
              건너뛰기
            </Button>
          ) : null,
      },
    ],
    [plan, onSkip, skipping],
  );
}

function PlanDetail({ planId }: { planId: number | null }) {
  const detail = useGeoRelease(planId);
  const skip = useSkipGeoReleaseItemMutation();
  const replan = useReplanGeoReleaseMutation();
  const confirm = useConfirm();
  const [skipping, setSkipping] = useState<number | null>(null);
  const plan = detail.data?.data.plan ?? null;

  const onSkip = async (item: GeoReleaseItemRecord) => {
    if (!plan) return;
    const ok = await confirm({
      title: `항목 ${item.position}(${item.operation_key})을 건너뛸까요?`,
      description:
        "건너뛴 항목의 dataset은 커버리지 분모에서 빠진다. MOIS처럼 수동 실행한 항목은 그 run이 끝난 뒤 건너뛴다.",
      confirmLabel: "건너뛰기",
    });
    if (!ok) return;
    setSkipping(item.position);
    skip.mutate(
      { planId: plan.plan_id, position: item.position },
      { onSettled: () => setSkipping(null) },
    );
  };
  const columns = useItemColumns(
    plan ?? ({ state: "done" } as GeoReleasePlanRecord),
    (item) => void onSkip(item),
    skipping,
  );

  if (planId === null) {
    return (
      <SectionCard description="계획 행을 선택하면 항목과 커버리지를 봅니다." title="계획 상세">
        <p className="text-xs text-text-tertiary">계획이 없거나 선택되지 않았습니다.</p>
      </SectionCard>
    );
  }
  const onReplan = async () => {
    if (!plan) return;
    const ok = await confirm({
      title: `계획 ${plan.plan_id}을 다시 계획할까요?`,
      description:
        "같은 토큰으로 plan_seq + 1 새 계획을 만들고 지금 활성 계획은 대체된다. 누를 때마다 계획이 하나 더 생긴다.",
      confirmLabel: "다시 계획",
    });
    if (ok) replan.mutate(plan.plan_id);
  };
  const errors = [
    detail.error ? `상세: ${detail.error.message}` : null,
    skip.error ? `건너뛰기: ${skip.error.message}` : null,
    replan.error ? `다시 계획: ${replan.error.message}` : null,
  ].filter((line): line is string => line !== null);

  return (
    <SectionCard
      actions={
        plan && canReplan(plan) ? (
          <Button
            loading={replan.isPending}
            size="sm"
            type="button"
            variant="outline"
            onClick={() => void onReplan()}
          >
            <RotateCcwIcon data-icon="inline-start" />
            다시 계획
          </Button>
        ) : null
      }
      description={
        plan ? (
          <span className="font-mono">
            #{plan.plan_id} · seq {plan.plan_seq} · {shortId(plan.geo_data_token, 16)}
          </span>
        ) : (
          NULL_GLYPH
        )
      }
      title="계획 상세"
    >
      {errors.length > 0 ? (
        <Alert variant="destructive">
          <AlertTitle>요청 실패</AlertTitle>
          <AlertDescription>
            {errors.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </AlertDescription>
        </Alert>
      ) : null}
      {plan ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {planStatus(plan.state)}
            {plan.residual_stale !== null ? (
              <span className="text-xs text-text-secondary">
                잔여 stale {formatCount(plan.residual_stale)}
              </span>
            ) : null}
          </div>
          {detail.data ? <CoverageGauge coverage={detail.data.data.coverage} /> : null}
          <DataTable
            ariaLabel="계획 항목"
            columns={columns}
            data={plan.items}
            emptyState={{ title: "항목이 없습니다.", description: "기준선 계획은 항목을 만들지 않는다." }}
            getRowId={(row) => String(row.position)}
            manualSorting={false}
            rowTestId={(row) => `geo-release-item-${row.position}`}
          />
        </>
      ) : (
        <DataTable
          ariaLabel="계획 항목"
          columns={columns}
          data={[]}
          isLoading={detail.isLoading}
        />
      )}
    </SectionCard>
  );
}

function usePlanColumns(): ColumnDef<GeoReleasePlanRecord, unknown>[] {
  return useMemo<ColumnDef<GeoReleasePlanRecord, unknown>[]>(
    () => [
      {
        accessorKey: "plan_id",
        header: "계획",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            #{row.original.plan_id} · seq {row.original.plan_seq}
          </span>
        ),
      },
      {
        accessorKey: "state",
        header: "상태",
        cell: ({ row }) => planStatus(row.original.state),
      },
      {
        accessorKey: "observed_at",
        header: "관측",
        cell: ({ row }) => formatDateTime(row.original.observed_at),
      },
    ],
    [],
  );
}

export function GeoReleasesClient() {
  const list = useGeoReleases();
  const detect = useDetectGeoReleaseMutation();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [lastDetect, setLastDetect] = useState<GeoReleaseDetectResponse | null>(null);
  const plans = useMemo(() => list.data?.data.plans ?? [], [list.data]);
  const selected =
    plans.find((plan) => plan.plan_id === selectedId) ?? plans[0] ?? null;
  const columns = usePlanColumns();

  const runDetect = () => {
    detect.mutate(undefined, {
      onSuccess: (response) => {
        setLastDetect(response);
        if (response.data.plan) setSelectedId(response.data.plan.plan_id);
      },
    });
  };

  return (
    <AdminShell
      actions={
        <>
          <Button
            loading={list.isFetching}
            type="button"
            variant="outline"
            onClick={() => void list.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          <Button loading={detect.isPending} type="button" onClick={runDetect}>
            <RadarIcon data-icon="inline-start" />
            지금 감지
          </Button>
        </>
      }
      description="kor-travel-geo 새 데이터셋으로 geo 유도 값을 다시 적재하는 계획(ADR-109)."
      title="geo 릴리스"
    >
      <div className="flex flex-col gap-6">
        {list.error || detect.error ? (
          <Alert variant="destructive">
            <AlertTitle>요청 실패</AlertTitle>
            <AlertDescription>
              {list.error ? <p>목록: {list.error.message}</p> : null}
              {detect.error ? <p>지금 감지: {detect.error.message}</p> : null}
            </AlertDescription>
          </Alert>
        ) : null}
        {lastDetect ? (
          <Alert>
            <AlertTitle>감지 결과</AlertTitle>
            <AlertDescription>
              <p data-testid="geo-release-detect-outcome">
                {DETECT_OUTCOME_TEXT[lastDetect.data.outcome]}
                {lastDetect.data.plan ? ` 계획 #${lastDetect.data.plan.plan_id}.` : ""}
              </p>
            </AlertDescription>
            <AlertAction>
              <Button
                aria-label="감지 결과 닫기"
                size="icon-sm"
                type="button"
                variant="ghost"
                onClick={() => setLastDetect(null)}
              >
                <XIcon />
              </Button>
            </AlertAction>
          </Alert>
        ) : null}

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
          <div className="flex min-w-0 flex-col gap-6">
            <PlanDetail planId={selected?.plan_id ?? null} />
          </div>
          <div className="flex min-w-0 flex-col gap-6">
            <CurrentDatasetCard data={list.data?.data} />
            <SectionCard
              description={`${formatCount(plans.length)}건 — 최신 순`}
              title="계획 목록"
            >
              <DataTable
                ariaLabel="geo 릴리스 계획"
                columns={columns}
                data={plans}
                emptyState={{
                  title: "계획이 없습니다.",
                  description: "첫 토큰은 기준선으로만 기록된다 — 토큰이 바뀌면 계획이 생긴다.",
                }}
                getRowId={(row) => String(row.plan_id)}
                isLoading={list.isLoading}
                isRowActive={(row) => selected?.plan_id === row.plan_id}
                manualSorting={false}
                rowTestId={(row) => `geo-release-plan-${row.plan_id}`}
                onRowClick={(row) => setSelectedId(row.plan_id)}
              />
            </SectionCard>
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
