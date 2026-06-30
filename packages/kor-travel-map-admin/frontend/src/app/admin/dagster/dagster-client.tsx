"use client";

import { useEffect, useMemo, useState } from "react";

import { type ColumnDef } from "@tanstack/react-table";

import {
  ActivityIcon,
  AlertTriangleIcon,
  BoxesIcon,
  CalendarClockIcon,
  CheckIcon,
  Clock3Icon,
  ExternalLinkIcon,
  GitBranchIcon,
  PencilIcon,
  PlayIcon,
  PowerIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";

import {
  DAGSTER_UI_URL,
  type DagsterGraphqlError,
  type DagsterInstigationTick,
  type DagsterRepository,
  type DagsterRunEvent,
  type DagsterRunSummary,
  type DagsterSchedule,
  type DagsterScheduleCommandResponse,
  useDagsterScheduleCommand,
  useDagsterRunDetail,
  useMarkDagsterNuxSeen,
  usePatchDagsterSchedule,
  useDagsterSummary,
} from "@/api/dagster";
import { AdminShell } from "@/components/admin-shell";
import { statusLabel } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable } from "@/components/ui/data-table";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const terminalStatus = new Set(["SUCCESS", "FAILURE", "CANCELED"]);
const runTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "short",
  timeStyle: "medium",
});
const checkedAtFormatter = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function statusVariant(status: string) {
  if (status === "ok" || status === "SUCCESS" || status === "STARTED") {
    return "secondary" as const;
  }
  if (
    status === "unavailable" ||
    status === "error" ||
    status === "FAILURE" ||
    status === "CANCELED"
  ) {
    return "destructive" as const;
  }
  return "outline" as const;
}

function epochToMilliseconds(value: number): number {
  const absolute = Math.abs(value);
  if (absolute >= 100_000_000_000_000_000) return value / 1_000_000;
  if (absolute >= 100_000_000_000_000) return value / 1_000;
  if (absolute >= 100_000_000_000) return value;
  return value * 1000;
}

function formatEpoch(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "-";
  }
  return runTimeFormatter.format(new Date(epochToMilliseconds(value)));
}

function formatCheckedAt(value: string | undefined) {
  if (!value) {
    return "-";
  }
  return checkedAtFormatter.format(new Date(value));
}

function formatEventTimestamp(value: string | null | undefined) {
  if (!value) {
    return "-";
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return runTimeFormatter.format(new Date(epochToMilliseconds(numeric)));
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return runTimeFormatter.format(date);
}

function shortRunId(runId: string) {
  return runId.length > 12 ? `${runId.slice(0, 12)}...` : runId;
}

function dagsterRunUrl(runId: string) {
  return `${DAGSTER_UI_URL.replace(/\/+$/, "")}/runs/${encodeURIComponent(runId)}`;
}

function dagsterRunsUrl(status: string) {
  return `${DAGSTER_UI_URL.replace(/\/+$/, "")}/runs?statuses=${encodeURIComponent(status)}`;
}

function shortCodeName(value: string) {
  return value.length > 42 ? `${value.slice(0, 42)}...` : value;
}

function scheduleCommandLabel(command: string) {
  const labels: Record<string, string> = {
    default: "기본값으로 되돌리기",
    reset: "상태 초기화",
    run: "즉시 실행",
    start: "스케줄 시작",
    stop: "스케줄 중지",
    update: "스케줄 수정",
  };
  return labels[command] ?? command;
}

type ScheduleFrequency =
  | "daily"
  | "daily_multi"
  | "hourly"
  | "monthly"
  | "weekly";

interface ScheduleEditDraft {
  frequency: ScheduleFrequency;
  minute: string;
  monthDay: string;
  reason: string;
  time: string;
  times: string;
  weekday: string;
}

const WEEKDAY_OPTIONS = [
  { label: "일요일", value: "0" },
  { label: "월요일", value: "1" },
  { label: "화요일", value: "2" },
  { label: "수요일", value: "3" },
  { label: "목요일", value: "4" },
  { label: "금요일", value: "5" },
  { label: "토요일", value: "6" },
] as const;

const FREQUENCY_LABELS: Record<ScheduleFrequency, string> = {
  daily: "매일",
  daily_multi: "매일 여러 번",
  hourly: "매시간",
  monthly: "매월",
  weekly: "매주",
};

const SCHEDULE_PROVIDER_RULES: Array<{ pattern: RegExp; provider: string }> = [
  { pattern: /airkorea/, provider: "python-airkorea-api" },
  { pattern: /datagokr_cultural_festivals|standard_/, provider: "data.go.kr-standard" },
  { pattern: /datagokr_/, provider: "python-datagokr-api" },
  { pattern: /khoa/, provider: "python-khoa-api" },
  { pattern: /kma/, provider: "python-kma-api" },
  { pattern: /knps/, provider: "python-knps-api" },
  { pattern: /kor_travel_concierge/, provider: "kor-travel-concierge-youtube" },
  { pattern: /krairport/, provider: "python-krairport-api" },
  { pattern: /krex/, provider: "python-krex-api" },
  { pattern: /krforest/, provider: "python-krforest-api" },
  { pattern: /krheritage/, provider: "python-krheritage-api" },
  { pattern: /mcst/, provider: "python-mcst-api" },
  { pattern: /mois/, provider: "python-mois-api" },
  { pattern: /opinet/, provider: "python-opinet-api" },
  { pattern: /visitkorea/, provider: "python-visitkorea-api" },
];

function pad2(value: number | string) {
  return String(value).padStart(2, "0");
}

function parseCronParts(cron: string | null | undefined) {
  const parts = (cron ?? "").trim().split(/\s+/);
  return parts.length === 5 ? parts : null;
}

function clockText(hour: string | number, minute: string | number) {
  return `${pad2(hour)}:${pad2(minute)}`;
}

function parseClock(value: string, label: string) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) {
    throw new Error(`${label}은 HH:MM 형식으로 입력하세요.`);
  }
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) {
    throw new Error(`${label}의 시간은 00~23 사이여야 합니다.`);
  }
  if (!Number.isInteger(minute) || minute < 0 || minute > 59) {
    throw new Error(`${label}의 분은 00~59 사이여야 합니다.`);
  }
  return { hour, minute, text: clockText(hour, minute) };
}

function parseMinute(value: string) {
  const minute = Number(value.trim());
  if (!Number.isInteger(minute) || minute < 0 || minute > 59) {
    throw new Error("분은 0~59 사이의 정수여야 합니다.");
  }
  return minute;
}

function parseMonthDay(value: string) {
  const day = Number(value.trim());
  if (!Number.isInteger(day) || day < 1 || day > 31) {
    throw new Error("월 실행일은 1~31 사이의 정수여야 합니다.");
  }
  return day;
}

function parseDailyTimes(value: string) {
  const clocks = value
    .split(/[,，]\s*|\s+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item, index) => parseClock(item, `실행 시각 ${index + 1}`));
  if (clocks.length === 0) {
    throw new Error("실행 시각을 하나 이상 입력하세요.");
  }
  const minute = clocks[0].minute;
  if (clocks.some((clock) => clock.minute !== minute)) {
    throw new Error("매일 여러 번 실행은 같은 분 단위의 시각만 함께 저장할 수 있습니다.");
  }
  const hours = Array.from(new Set(clocks.map((clock) => clock.hour))).sort(
    (left, right) => left - right,
  );
  return {
    cron: `${minute} ${hours.join(",")} * * *`,
    text: hours.map((hour) => clockText(hour, minute)).join(", "),
  };
}

function draftFromCron(cron: string | null | undefined): ScheduleEditDraft {
  const parts = parseCronParts(cron);
  if (!parts) {
    return {
      frequency: "daily",
      minute: "0",
      monthDay: "1",
      reason: "",
      time: "06:00",
      times: "06:00",
      weekday: "1",
    };
  }

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
  if (month === "*" && hour === "*" && dayOfMonth === "*" && dayOfWeek === "*") {
    return {
      frequency: "hourly",
      minute,
      monthDay: "1",
      reason: "",
      time: "06:00",
      times: clockText(6, minute),
      weekday: "1",
    };
  }
  if (month === "*" && dayOfMonth === "*" && dayOfWeek === "*" && hour.includes(",")) {
    return {
      frequency: "daily_multi",
      minute,
      monthDay: "1",
      reason: "",
      time: clockText(hour.split(",")[0] ?? "6", minute),
      times: hour
        .split(",")
        .map((item) => clockText(item, minute))
        .join(", "),
      weekday: "1",
    };
  }
  if (month === "*" && dayOfMonth === "*" && dayOfWeek === "*") {
    return {
      frequency: "daily",
      minute,
      monthDay: "1",
      reason: "",
      time: clockText(hour, minute),
      times: clockText(hour, minute),
      weekday: "1",
    };
  }
  if (month === "*" && dayOfMonth === "*") {
    return {
      frequency: "weekly",
      minute,
      monthDay: "1",
      reason: "",
      time: clockText(hour, minute),
      times: clockText(hour, minute),
      weekday: dayOfWeek,
    };
  }
  return {
    frequency: "monthly",
    minute,
    monthDay: dayOfMonth === "*" ? "1" : dayOfMonth,
    reason: "",
    time: clockText(hour === "*" ? "6" : hour, minute),
    times: clockText(hour === "*" ? "6" : hour, minute),
    weekday: "1",
  };
}

function buildCronFromDraft(draft: ScheduleEditDraft) {
  if (draft.frequency === "hourly") {
    return `${parseMinute(draft.minute)} * * * *`;
  }
  if (draft.frequency === "daily_multi") {
    return parseDailyTimes(draft.times).cron;
  }
  const clock = parseClock(draft.time, "실행 시각");
  if (draft.frequency === "daily") {
    return `${clock.minute} ${clock.hour} * * *`;
  }
  if (draft.frequency === "weekly") {
    const weekday = Number(draft.weekday);
    if (!Number.isInteger(weekday) || weekday < 0 || weekday > 6) {
      throw new Error("요일을 선택하세요.");
    }
    return `${clock.minute} ${clock.hour} * * ${weekday}`;
  }
  return `${clock.minute} ${clock.hour} ${parseMonthDay(draft.monthDay)} * *`;
}

function sentenceFromDraft(draft: ScheduleEditDraft) {
  if (draft.frequency === "hourly") {
    return `매시간 ${pad2(parseMinute(draft.minute))}분에 실행`;
  }
  if (draft.frequency === "daily_multi") {
    return `매일 ${parseDailyTimes(draft.times).text}에 실행`;
  }
  const clock = parseClock(draft.time, "실행 시각").text;
  if (draft.frequency === "daily") {
    return `매일 ${clock}에 실행`;
  }
  if (draft.frequency === "weekly") {
    const weekday =
      WEEKDAY_OPTIONS.find((item) => item.value === draft.weekday)?.label ?? "선택한 요일";
    return `매주 ${weekday} ${clock}에 실행`;
  }
  return `매월 ${parseMonthDay(draft.monthDay)}일 ${clock}에 실행`;
}

function sentenceFromCron(cron: string | null | undefined, timezone?: string | null) {
  try {
    const text = sentenceFromDraft(draftFromCron(cron));
    return timezone ? `${text} (${timezone})` : text;
  } catch {
    return timezone
      ? `해석이 필요한 반복 규칙입니다 (${timezone})`
      : "해석이 필요한 반복 규칙입니다";
  }
}

function defaultScheduleSentence(schedule: DagsterSchedule) {
  if (!schedule.default_cron_schedule) {
    return null;
  }
  return `기본값: ${sentenceFromCron(
    schedule.default_cron_schedule,
    schedule.execution_timezone,
  )}`;
}

function scheduleDatasetKey(scheduleName: string) {
  const match =
    /^feature_(?:event|geometry|notice|place|price|weather)_(.+?)_(?:daily|hourly|monthly|twice_daily|weekly)_schedule$/.exec(
      scheduleName,
    );
  return match?.[1] ?? null;
}

function scheduleProviderHref(scheduleName: string) {
  const provider = SCHEDULE_PROVIDER_RULES.find((rule) =>
    rule.pattern.test(scheduleName),
  )?.provider;
  if (!provider) {
    return null;
  }
  const params = new URLSearchParams({ provider });
  const datasetKey = scheduleDatasetKey(scheduleName);
  if (datasetKey) {
    params.set("dataset_key", datasetKey);
  }
  return `/ops/providers?${params.toString()}`;
}

function graphqlErrorText(error: DagsterGraphqlError | null | undefined) {
  if (!error) {
    return null;
  }
  if (error.class_name && error.message) {
    return `${error.class_name}: ${error.message}`;
  }
  return error.message ?? error.class_name ?? error.stack?.[0] ?? "Dagster error";
}

function graphqlErrorStack(error: DagsterGraphqlError | null | undefined) {
  if (!error?.stack?.length) {
    return null;
  }
  return error.stack.join("\n");
}

function SummaryCard({
  title,
  value,
  description,
  icon: Icon,
  href,
  tone,
}: {
  title: string;
  value: string;
  description: string;
  href?: string;
  icon: typeof ActivityIcon;
  tone: "blue" | "green" | "amber" | "slate";
}) {
  const toneClass = {
    blue: "bg-sky-50 text-sky-700 ring-sky-200",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-700 ring-amber-200",
    slate: "bg-slate-50 text-slate-700 ring-slate-200",
  }[tone];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <CardAction>
          {href ? (
            <a
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
              href={href}
              rel="noreferrer"
              target="_blank"
            >
              <ExternalLinkIcon data-icon="inline-start" />
              목록 보기
            </a>
          ) : (
          <span
            className={cn(
              "inline-flex size-8 items-center justify-center rounded-md ring-1",
              toneClass,
            )}
          >
            <Icon className="size-4" />
          </span>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <div className="text-2xl font-semibold">{value}</div>
        <p className="text-xs text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

function TickRows({
  ticks,
  onSelectRun,
}: {
  ticks: DagsterInstigationTick[];
  onSelectRun: (runId: string) => void;
}) {
  if (ticks.length === 0) {
    return <span className="text-xs text-muted-foreground">최근 tick 없음</span>;
  }

  return (
    <details className="rounded-md border bg-background/60">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground">
        최근 실행 기록 {ticks.length}건
      </summary>
      <div className="flex flex-col gap-2 border-t p-2">
        {ticks.map((tick) => (
          <div
            className="rounded-md bg-background p-2 text-xs"
            key={tick.tick_id}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <Badge variant={statusVariant(tick.status)}>
                  {statusLabel(tick.status)}
                </Badge>
                <span className="truncate font-mono text-muted-foreground">
                  {tick.tick_id}
                </span>
              </div>
              <span className="text-muted-foreground">
                {formatEpoch(tick.timestamp)}
              </span>
            </div>
            {tick.skip_reason ? (
              <p className="mt-2 break-words text-muted-foreground">
                {tick.skip_reason}
              </p>
            ) : null}
            {graphqlErrorText(tick.error) ? (
              <p className="mt-2 break-words text-destructive">
                {graphqlErrorText(tick.error)}
              </p>
            ) : null}
            {graphqlErrorStack(tick.error) ? (
              <details className="mt-2">
                <summary className="cursor-pointer text-destructive">
                  stack
                </summary>
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-destructive/10 p-2 text-[11px] text-destructive">
                  {graphqlErrorStack(tick.error)}
                </pre>
              </details>
            ) : null}
            {tick.run_ids?.length ? (
              <div className="mt-2 flex flex-wrap gap-1">
                {tick.run_ids.map((runId) => (
                  <Button
                    className="font-mono"
                    key={runId}
                    size="xs"
                    type="button"
                    variant="ghost"
                    onClick={() => onSelectRun(runId)}
                  >
                    {shortRunId(runId)}
                  </Button>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </details>
  );
}

function InstigationList({
  title,
  items,
  onSelectRun,
}: {
  title: string;
  items: Array<{
    name: string;
    status?: string | null;
    cron_schedule?: string | null;
    execution_timezone?: string | null;
    recent_ticks?: DagsterInstigationTick[];
  }>;
  onSelectRun: (runId: string) => void;
}) {
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <div className="mb-2 text-sm font-medium">{title}</div>
      <div className="flex flex-col gap-3">
        {items.length === 0 ? (
          <span className="text-xs text-muted-foreground">없음</span>
        ) : null}
        {items.map((item) => (
          <div className="flex flex-col gap-2" key={item.name}>
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="truncate font-mono">{item.name}</span>
              <Badge variant={statusVariant(item.status ?? "")}>
                {statusLabel(item.status ?? "unknown")}
              </Badge>
            </div>
            {item.cron_schedule ? (
              <div className="text-xs text-muted-foreground">
                {item.cron_schedule}
                {item.execution_timezone ? ` · ${item.execution_timezone}` : ""}
              </div>
            ) : null}
            <TickRows
              ticks={item.recent_ticks ?? []}
              onSelectRun={onSelectRun}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function ScheduleControls({
  schedules,
  onSelectRun,
}: {
  schedules: DagsterSchedule[];
  onSelectRun: (runId: string) => void;
}) {
  const command = useDagsterScheduleCommand();
  const patchSchedule = usePatchDagsterSchedule();
  const [editing, setEditing] = useState<DagsterSchedule | null>(null);
  const [draft, setDraft] = useState<ScheduleEditDraft>(() =>
    draftFromCron(null),
  );
  const [reasonDraft, setReasonDraft] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<
    DagsterScheduleCommandResponse["data"] | null
  >(null);
  const pending = command.isPending || patchSchedule.isPending;
  const error = command.error ?? patchSchedule.error;

  const beginEdit = (schedule: DagsterSchedule) => {
    setEditing(schedule);
    setDraft(draftFromCron(schedule.cron_schedule ?? schedule.default_cron_schedule));
    setReasonDraft("");
    setEditError(null);
  };
  const closeEdit = () => {
    setEditing(null);
    setEditError(null);
  };
  const updateDraft = <K extends keyof ScheduleEditDraft>(
    key: K,
    value: ScheduleEditDraft[K],
  ) => setDraft((current) => ({ ...current, [key]: value }));
  const submitEdit = () => {
    if (!editing) return;
    let cronSchedule: string;
    try {
      cronSchedule = buildCronFromDraft(draft);
    } catch (error) {
      setEditError(error instanceof Error ? error.message : String(error));
      return;
    }
    setLastResult(null);
    setEditError(null);
    patchSchedule.mutate({
      scheduleName: editing.name,
      cronSchedule,
      reason: reasonDraft || "운영 화면 스케줄 수정",
    }, {
      onSuccess: (response) => {
        closeEdit();
        setLastResult(response.data);
      },
    });
  };
  const runCommand = (
    scheduleName: string,
    nextCommand: "default" | "reset" | "run" | "start" | "stop",
  ) => {
    setLastResult(null);
    command.mutate({
      scheduleName,
      command: nextCommand,
      reason: `운영 화면 ${scheduleCommandLabel(nextCommand)}`,
    }, {
      onSuccess: (response) => {
        setLastResult(response.data);
      },
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>스케줄</CardTitle>
        <CardDescription>
          반복 주기와 실행 시각으로 스케줄을 조정합니다. 기본값은 제공자 호출 한도의 약 90% 수준으로 낮게 잡고, 파일 다운로드 계열은 월 1회를 기준으로 둡니다.
        </CardDescription>
        <CardAction>
          <Clock3Icon className="text-muted-foreground" />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>스케줄 명령 실패</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : null}
        {lastResult ? (
          <Alert
            variant={lastResult.status === "ok" ? "default" : "destructive"}
          >
            <Clock3Icon data-icon="inline-start" />
            <AlertTitle>스케줄 명령 결과</AlertTitle>
            <AlertDescription>
              <div className="flex flex-col gap-1">
                <div>
                  {scheduleCommandLabel(lastResult.command)} ·{" "}
                  <span className="font-mono">{lastResult.schedule_name}</span>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  {lastResult.schedule_status ? (
                    <span>상태 {statusLabel(lastResult.schedule_status)}</span>
                  ) : null}
                  {lastResult.cron_schedule ? (
                    <span>{sentenceFromCron(lastResult.cron_schedule)}</span>
                  ) : null}
                  {lastResult.reloaded ? <span>코드 위치 새로고침 요청됨</span> : null}
                  {lastResult.run_id ? (
                    <span className="font-mono">run {shortRunId(lastResult.run_id)}</span>
                  ) : null}
                </div>
                {lastResult.errors?.length ? (
                  <div className="text-destructive">
                    {lastResult.errors.join(" / ")}
                  </div>
                ) : null}
              </div>
            </AlertDescription>
          </Alert>
        ) : null}
        {schedules.length === 0 ? (
          <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            등록된 스케줄이 없습니다.
          </div>
        ) : null}
        <div className="grid gap-2">
          {schedules.map((schedule) => {
            const isRunning = schedule.status === "RUNNING";
            const providerHref = scheduleProviderHref(schedule.name);
            const defaultSentence = defaultScheduleSentence(schedule);
            const toggleCommand = isRunning ? "stop" : "start";
            return (
              <div
                className="grid gap-2 rounded-md border bg-background p-3 lg:grid-cols-[minmax(0,1fr)_auto]"
                data-testid={`dagster-schedule-row-${schedule.name}`}
                key={schedule.name}
              >
                <div className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="min-w-0 truncate text-sm font-medium">
                      {schedule.description ?? "스케줄"}
                    </span>
                    <Badge variant={statusVariant(schedule.status ?? "")}>
                      {statusLabel(schedule.status ?? "unknown")}
                    </Badge>
                    {schedule.override_cron_schedule ? (
                      <Badge variant="outline">수정됨</Badge>
                    ) : null}
                    {providerHref ? (
                      <Link
                        className={cn(buttonVariants({ variant: "outline", size: "xs" }))}
                        href={providerHref}
                      >
                        <ExternalLinkIcon data-icon="inline-start" />
                        제공자 상태
                      </Link>
                    ) : null}
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    {sentenceFromCron(
                      schedule.cron_schedule,
                      schedule.execution_timezone,
                    )}
                  </div>
                  {defaultSentence &&
                  schedule.default_cron_schedule !== schedule.cron_schedule ? (
                    <div className="mt-1 text-xs text-muted-foreground">
                      {defaultSentence}
                    </div>
                  ) : null}
                  <div
                    className="mt-1 truncate font-mono text-[11px] text-muted-foreground"
                    title={schedule.name}
                  >
                    {schedule.name}
                  </div>
                  {schedule.schedule_note ? (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {schedule.schedule_note}
                    </p>
                  ) : null}
                  {schedule.recent_ticks?.length ? (
                    <div className="mt-3">
                      <TickRows
                        ticks={schedule.recent_ticks}
                        onSelectRun={onSelectRun}
                      />
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-1 lg:justify-end">
                  <Button
                    disabled={pending}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => runCommand(schedule.name, "run")}
                  >
                    <PlayIcon data-icon="inline-start" />
                    즉시 실행
                  </Button>
                  <Button
                    disabled={pending}
                    size="sm"
                    type="button"
                    variant={isRunning ? "destructive" : "default"}
                    onClick={() =>
                      runCommand(schedule.name, toggleCommand)
                    }
                  >
                    {pending ? (
                      <RefreshCwIcon className="animate-spin" data-icon="inline-start" />
                    ) : isRunning ? (
                      <PowerIcon data-icon="inline-start" />
                    ) : (
                      <PlayIcon data-icon="inline-start" />
                    )}
                    {isRunning ? "스케줄 중지" : "스케줄 시작"}
                  </Button>
                  <Button
                    disabled={pending}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => beginEdit(schedule)}
                  >
                    <PencilIcon data-icon="inline-start" />
                    스케줄 수정
                  </Button>
                  <Button
                    disabled={pending}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => runCommand(schedule.name, "default")}
                  >
                    <RotateCcwIcon data-icon="inline-start" />
                    기본값으로 되돌리기
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
      {editing ? (
        <div
          aria-labelledby="schedule-edit-dialog-title"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center overflow-auto bg-black/45 p-3"
          role="dialog"
        >
          <div className="flex max-h-[calc(100dvh-1.5rem)] w-full max-w-2xl flex-col overflow-hidden rounded-lg border bg-background shadow-xl">
            <div className="flex shrink-0 items-start justify-between gap-3 border-b px-4 py-3">
              <div className="min-w-0">
                <div className="font-medium" id="schedule-edit-dialog-title">
                  스케줄 수정
                </div>
                <div className="truncate font-mono text-xs text-muted-foreground">
                  {editing.name}
                </div>
              </div>
              <Button
                aria-label="스케줄 수정 닫기"
                size="icon"
                type="button"
                variant="ghost"
                onClick={closeEdit}
              >
                <XIcon />
              </Button>
            </div>
            <div className="min-h-0 overflow-auto px-4 py-4">
              <div className="grid gap-4">
                {editError ? (
                  <Alert variant="destructive">
                    <AlertTriangleIcon data-icon="inline-start" />
                    <AlertTitle>스케줄 입력 확인</AlertTitle>
                    <AlertDescription>{editError}</AlertDescription>
                  </Alert>
                ) : null}
                <div className="rounded-md bg-muted/50 p-3 text-sm">
                  <div className="flex items-center gap-2 font-medium">
                    <CalendarClockIcon className="size-4" />
                    {(() => {
                      try {
                        return sentenceFromDraft(draft);
                      } catch {
                        return "반복 주기와 실행 시각을 확인하세요.";
                      }
                    })()}
                  </div>
                  {editing.execution_timezone ? (
                    <div className="mt-1 text-xs text-muted-foreground">
                      시간대 {editing.execution_timezone}
                    </div>
                  ) : null}
                </div>
                <label className="grid gap-1 text-sm">
                  <span className="font-medium">반복 주기</span>
                  <select
                    aria-label={`${editing.name} frequency`}
                    className="h-10 rounded-md border bg-background px-3 text-sm"
                    value={draft.frequency}
                    onChange={(event) =>
                      updateDraft(
                        "frequency",
                        event.target.value as ScheduleFrequency,
                      )
                    }
                  >
                    {Object.entries(FREQUENCY_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {draft.frequency === "hourly" ? (
                  <label className="grid gap-1 text-sm">
                    <span className="font-medium">매시간 실행할 분</span>
                    <input
                      aria-label={`${editing.name} minute`}
                      className="h-10 rounded-md border bg-background px-3 text-sm"
                      inputMode="numeric"
                      max={59}
                      min={0}
                      type="number"
                      value={draft.minute}
                      onChange={(event) =>
                        updateDraft("minute", event.target.value)
                      }
                    />
                  </label>
                ) : null}
                {draft.frequency === "daily_multi" ? (
                  <label className="grid gap-1 text-sm">
                    <span className="font-medium">하루 중 실행 시각</span>
                    <input
                      aria-label={`${editing.name} times`}
                      className="h-10 rounded-md border bg-background px-3 text-sm"
                      placeholder="06:28, 18:28"
                      value={draft.times}
                      onChange={(event) =>
                        updateDraft("times", event.target.value)
                      }
                    />
                  </label>
                ) : null}
                {draft.frequency !== "hourly" &&
                draft.frequency !== "daily_multi" ? (
                  <label className="grid gap-1 text-sm">
                    <span className="font-medium">실행 시각</span>
                    <input
                      aria-label={`${editing.name} time`}
                      className="h-10 rounded-md border bg-background px-3 text-sm"
                      type="time"
                      value={draft.time}
                      onChange={(event) => updateDraft("time", event.target.value)}
                    />
                  </label>
                ) : null}
                {draft.frequency === "weekly" ? (
                  <label className="grid gap-1 text-sm">
                    <span className="font-medium">요일</span>
                    <select
                      aria-label={`${editing.name} weekday`}
                      className="h-10 rounded-md border bg-background px-3 text-sm"
                      value={draft.weekday}
                      onChange={(event) =>
                        updateDraft("weekday", event.target.value)
                      }
                    >
                      {WEEKDAY_OPTIONS.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                {draft.frequency === "monthly" ? (
                  <label className="grid gap-1 text-sm">
                    <span className="font-medium">매월 실행일</span>
                    <input
                      aria-label={`${editing.name} month day`}
                      className="h-10 rounded-md border bg-background px-3 text-sm"
                      inputMode="numeric"
                      max={31}
                      min={1}
                      type="number"
                      value={draft.monthDay}
                      onChange={(event) =>
                        updateDraft("monthDay", event.target.value)
                      }
                    />
                  </label>
                ) : null}
                <label className="grid gap-1 text-sm">
                  <span className="font-medium">수정 사유</span>
                  <input
                    aria-label={`${editing.name} reason`}
                    className="h-10 rounded-md border bg-background px-3 text-sm"
                    placeholder="예: 제공자 호출량 조정"
                    value={reasonDraft}
                    onChange={(event) => setReasonDraft(event.target.value)}
                  />
                </label>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t px-4 py-3">
              <Button
                disabled={pending}
                type="button"
                variant="outline"
                onClick={closeEdit}
              >
                <XIcon data-icon="inline-start" />
                취소
              </Button>
              <Button disabled={pending} type="button" onClick={submitEdit}>
                <CheckIcon data-icon="inline-start" />
                저장
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function RepositoryList({
  repositories,
  onSelectRun,
}: {
  repositories: DagsterRepository[];
  onSelectRun: (runId: string) => void;
}) {
  if (repositories.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">
        등록된 코드 위치가 없습니다.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {repositories.map((repository) => (
        <div
          key={`${repository.location_name}:${repository.name}`}
          className="rounded-md border bg-background p-4"
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="font-medium">코드 위치</div>
              <div
                className="max-w-full truncate font-mono text-xs text-muted-foreground"
                title={repository.location_name}
              >
                {repository.location_name}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {repository.name}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">{repository.jobs.length} jobs</Badge>
              <Badge variant="outline">{repository.asset_count} assets</Badge>
            </div>
          </div>

          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {repository.asset_groups.map((group) => (
              <div key={group.group_name} className="rounded-md bg-muted/60 p-2.5">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">{group.group_name}</span>
                  <Badge variant="secondary">{group.asset_count}</Badge>
                </div>
                <div className="mt-2 flex max-h-40 flex-col gap-1.5 overflow-auto pr-1">
                  {((group.asset_items ?? []).length > 0
                    ? (group.asset_items ?? [])
                    : group.assets.map((asset) => ({
                        display_name: asset,
                        name: asset,
                      }))
                  ).map((asset) => (
                    <div key={asset.name} className="min-w-0">
                      <div className="truncate text-xs font-medium">
                        {asset.display_name}
                      </div>
                      <div
                        className="truncate font-mono text-[11px] text-muted-foreground"
                        title={asset.name}
                      >
                        {shortCodeName(asset.name)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <InstigationList
              items={repository.sensors}
              title="센서"
              onSelectRun={onSelectRun}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function RunsTable({
  runs,
  selectedRunId,
  onSelectRun,
}: {
  runs: DagsterRunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const columns = useMemo<ColumnDef<DagsterRunSummary, unknown>[]>(
    () => [
      {
        id: "run",
        header: "실행",
        enableSorting: false,
        cell: ({ row }) => {
          const run = row.original;
          const selected = run.run_id === selectedRunId;
          return (
            <span className="font-mono text-xs">
              <Button
                className="font-mono"
                size="xs"
                type="button"
                variant={selected ? "secondary" : "ghost"}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectRun(run.run_id);
                }}
              >
                {shortRunId(run.run_id)}
              </Button>
            </span>
          );
        },
      },
      {
        id: "job",
        header: "작업",
        accessorFn: (run) => run.job_name ?? "-",
        cell: ({ row }) => row.original.job_name ?? "-",
      },
      {
        accessorKey: "status",
        header: "상태",
        cell: ({ row }) => (
          <Badge variant={statusVariant(row.original.status)}>
            {statusLabel(row.original.status)}
          </Badge>
        ),
      },
      {
        id: "updated",
        header: "수정",
        accessorFn: (run) =>
          run.update_time ?? run.end_time ?? run.start_time ?? 0,
        cell: ({ row }) => {
          const run = row.original;
          return (
            <span className="text-muted-foreground">
              {formatEpoch(run.update_time ?? run.end_time ?? run.start_time)}
            </span>
          );
        },
      },
      {
        id: "link",
        header: () => <span className="sr-only">엔진 실행 링크</span>,
        enableSorting: false,
        cell: ({ row }) => (
          <a
            className={cn(buttonVariants({ variant: "ghost", size: "icon-xs" }))}
            href={dagsterRunUrl(row.original.run_id)}
            rel="noreferrer"
            target="_blank"
            title="엔진 실행 열기"
            onClick={(event) => event.stopPropagation()}
          >
            <ExternalLinkIcon />
            <span className="sr-only">엔진 실행 열기</span>
          </a>
        ),
      },
    ],
    [onSelectRun, selectedRunId],
  );

  return (
    <DataTable
      columns={columns}
      data={runs}
      getRowId={(run) => run.run_id}
      emptyMessage="최근 실행이 없습니다."
      onRowClick={(run) => onSelectRun(run.run_id)}
      isRowActive={(run) => run.run_id === selectedRunId}
      manualSorting={false}
    />
  );
}

function RunEventsTable({ events }: { events: DagsterRunEvent[] }) {
  const columns = useMemo<ColumnDef<DagsterRunEvent, unknown>[]>(
    () => [
      {
        id: "time",
        header: "시각",
        // event log는 cursor 페이지네이션(event_has_more) — 서버 순서 유지, client 정렬 끔(#502).
        enableSorting: false,
        accessorFn: (event) => event.timestamp ?? "",
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-muted-foreground">
            {formatEventTimestamp(row.original.timestamp)}
          </span>
        ),
      },
      {
        id: "event",
        header: "이벤트",
        enableSorting: false,
        cell: ({ row }) => {
          const event = row.original;
          return (
            <div className="flex flex-col gap-1">
              <Badge variant={event.level === "ERROR" ? "destructive" : "outline"}>
                {event.dagster_event_type ?? event.event_type}
              </Badge>
              {event.level ? (
                <span className="text-xs text-muted-foreground">
                  {statusLabel(event.level)}
                </span>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "step",
        header: "스텝",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.step_id ?? "-"}</span>
        ),
      },
      {
        id: "message",
        header: "메시지",
        enableSorting: false,
        cell: ({ row }) => {
          const errorText = graphqlErrorText(row.original.error);
          return (
            <div className="max-w-[34rem] whitespace-normal break-words text-sm">
              {errorText ? (
                <span className="text-destructive">{errorText}</span>
              ) : (
                (row.original.message ?? "-")
              )}
            </div>
          );
        },
      },
    ],
    [],
  );

  return (
    <DataTable
      columns={columns}
      data={events}
      getRowId={(event, index) => `${event.event_type}:${event.timestamp ?? index}`}
      emptyMessage="표시할 이벤트가 없습니다."
    />
  );
}

function RunDetailCard({ runId }: { runId: string | null }) {
  // event log cursor 페이지네이션 — 긴 run의 뒤쪽(실패) 이벤트로 전진하기 위함.
  // cursorStack: 2페이지부터의 after cursor 누적(1페이지는 after 없음). run 전환 시
  // 호출부의 key={runId}로 remount돼 1페이지로 리셋된다.
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const after = cursorStack.length > 0 ? cursorStack[cursorStack.length - 1] : null;

  const detail = useDagsterRunDetail(runId, 80, after);
  const data = detail.data?.data;
  const run = data?.run;
  const nextCursor = data?.event_cursor ?? null;
  const goNext = () => {
    if (data?.event_has_more && nextCursor) {
      setCursorStack((stack) => [...stack, nextCursor]);
    }
  };
  const goPrev = () => setCursorStack((stack) => stack.slice(0, -1));

  return (
    <Card>
      <CardHeader>
        <CardTitle>실행 상세</CardTitle>
        <CardDescription>선택한 실행의 이벤트와 실패 원인을 확인합니다.</CardDescription>
        <CardAction>
          {runId ? (
            <a
              className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }))}
              href={dagsterRunUrl(runId)}
              rel="noreferrer"
              target="_blank"
              title="엔진 실행 열기"
            >
              <ExternalLinkIcon />
              <span className="sr-only">엔진 실행 열기</span>
            </a>
          ) : (
            <ActivityIcon className="text-muted-foreground" />
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!runId ? (
          <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">
            최근 실행을 선택하면 이벤트와 실패 원인이 표시됩니다.
          </div>
        ) : null}

        {detail.isLoading ? <Skeleton className="h-72 w-full" /> : null}

        {detail.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>실행 상세 호출 실패</AlertTitle>
            <AlertDescription>{detail.error.message}</AlertDescription>
          </Alert>
        ) : null}

        {data?.errors?.length ? (
          <Alert variant={data.status === "not_found" ? "default" : "destructive"}>
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>실행 상세 상태 확인 필요</AlertTitle>
            <AlertDescription>{data.errors.join(" / ")}</AlertDescription>
          </Alert>
        ) : null}

        {data ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(data.status)}>
              {statusLabel(data.status)}
            </Badge>
            {run ? (
              <Badge variant={statusVariant(run.status)}>
                {statusLabel(run.status)}
              </Badge>
            ) : null}
            {data.event_has_more ? (
              <Badge variant="outline">events more</Badge>
            ) : null}
          </div>
        ) : null}

        {data?.failure_events?.length ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>실패 원인</AlertTitle>
            <AlertDescription>
              <div className="flex flex-col gap-3">
                {data.failure_reason ? (
                  <div className="break-words">{data.failure_reason}</div>
                ) : null}
                {data.failure_events.map((event, index) => {
                  const stack = graphqlErrorStack(event.error);
                  return (
                    <div
                      className="rounded-md bg-background/80 p-3"
                      key={`${event.event_type}:${event.timestamp ?? index}`}
                    >
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <Badge variant="destructive">
                          {event.dagster_event_type ?? event.event_type}
                        </Badge>
                        {event.step_id ? (
                          <span className="font-mono">{event.step_id}</span>
                        ) : null}
                        <span>{formatEventTimestamp(event.timestamp)}</span>
                      </div>
                      {event.message ? (
                        <div className="mt-2 break-words text-sm">
                          {event.message}
                        </div>
                      ) : null}
                      {stack ? (
                        <details className="mt-2">
                          <summary className="cursor-pointer text-xs">
                            stack
                          </summary>
                          <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2 text-[11px]">
                            {stack}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </AlertDescription>
          </Alert>
        ) : null}

        {run ? (
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs text-muted-foreground">실행 ID</div>
              <div className="mt-1 break-all font-mono text-xs">{run.run_id}</div>
            </div>
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs text-muted-foreground">작업</div>
              <div className="mt-1 text-sm">{run.job_name ?? "-"}</div>
            </div>
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs text-muted-foreground">시작</div>
              <div className="mt-1 text-sm">{formatEpoch(run.start_time)}</div>
            </div>
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs text-muted-foreground">수정</div>
              <div className="mt-1 text-sm">
                {formatEpoch(run.update_time ?? run.end_time)}
              </div>
            </div>
          </div>
        ) : null}

        {run && Object.keys(run.tags).length > 0 ? (
          <div className="rounded-md border bg-background p-3">
            <div className="mb-2 text-sm font-medium">태그</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(run.tags).map(([key, value]) => (
                <Badge className="max-w-full" key={key} variant="outline">
                  <span className="truncate">
                    {key}: {value}
                  </span>
                </Badge>
              ))}
            </div>
          </div>
        ) : null}

        {data ? <RunEventsTable events={data.events ?? []} /> : null}

        {data?.run ? (
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              이벤트 페이지 {cursorStack.length + 1} · {data.events?.length ?? 0}건
              {data.event_has_more ? " (뒤쪽 이벤트 더 있음)" : ""}
            </span>
            <div className="flex gap-1">
              <Button
                disabled={cursorStack.length === 0 || detail.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={goPrev}
              >
                이전
              </Button>
              <Button
                aria-label="다음 이벤트"
                disabled={!data.event_has_more || detail.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={goNext}
              >
                다음
              </Button>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function DagsterAdminClient() {
  const summary = useDagsterSummary(12);
  const { mutate: markNuxSeen, status: markNuxSeenStatus } =
    useMarkDagsterNuxSeen();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const data = summary.data?.data;
  const recentRuns = data?.recent_runs ?? [];
  const schedules =
    data?.repositories.flatMap((repository) => repository.schedules) ?? [];
  const activeRuns = recentRuns.filter(
    (run) => !terminalStatus.has(run.status),
  ).length;
  const failedRuns = data?.run_counts.FAILURE ?? 0;
  const fallbackRun = recentRuns.find((run) => run.status === "FAILURE") ?? recentRuns[0];
  const effectiveSelectedRunId = selectedRunId ?? fallbackRun?.run_id ?? null;

  useEffect(() => {
    if (data?.status !== "ok" || markNuxSeenStatus !== "idle") {
      return;
    }
    markNuxSeen();
  }, [data?.status, markNuxSeen, markNuxSeenStatus]);

  return (
    <AdminShell
      actions={
        <Button
          disabled={summary.isFetching}
          type="button"
          variant="outline"
          onClick={() => void summary.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description={`마지막 확인 ${formatCheckedAt(data?.checked_at)} · 스케줄과 실행 상태를 관리합니다.`}
      section="운영"
      title="작업 자동화"
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={statusVariant(data?.status ?? "loading")}>
            {statusLabel(data?.status ?? (summary.isError ? "error" : "loading"))}
          </Badge>
          {data?.version ? <Badge variant="outline">v{data.version}</Badge> : null}
        </div>

        {summary.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>작업 자동화 요약 호출 실패</AlertTitle>
            <AlertDescription>{summary.error.message}</AlertDescription>
          </Alert>
        ) : null}

        {data?.errors?.length ? (
          <Alert variant={data.status === "unavailable" ? "destructive" : "default"}>
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>작업 자동화 상태 확인 필요</AlertTitle>
            <AlertDescription>{data.errors.join(" / ")}</AlertDescription>
          </Alert>
        ) : null}

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {summary.isLoading ? (
            <>
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
            </>
          ) : (
            <>
              <SummaryCard
                title="코드 위치"
                value={String(data?.repository_count ?? 0)}
                description={`${data?.job_count ?? 0}개 작업 / ${data?.schedule_count ?? 0}개 스케줄`}
                icon={WorkflowIcon}
                tone="blue"
              />
              <SummaryCard
                title="에셋"
                value={String(data?.asset_count ?? 0)}
                description={`${data?.sensor_count ?? 0}개 감지 조건`}
                icon={BoxesIcon}
                tone="green"
              />
              <SummaryCard
                title="실행 중"
                value={String(activeRuns)}
                description="현재 진행 중인 실행"
                href={dagsterRunsUrl("STARTED")}
                icon={ActivityIcon}
                tone="amber"
              />
              <SummaryCard
                title="실패"
                value={String(failedRuns)}
                description="실패한 실행"
                href={dagsterRunsUrl("FAILURE")}
                icon={AlertTriangleIcon}
                tone="slate"
              />
            </>
          )}
        </section>

        {summary.isLoading ? <Skeleton className="h-56 w-full" /> : (
          <ScheduleControls schedules={schedules} onSelectRun={setSelectedRunId} />
        )}

        <section className="grid gap-4 xl:grid-cols-[minmax(28rem,0.9fr)_minmax(32rem,1.1fr)]">
          <Card id="recent-runs">
            <CardHeader>
              <CardTitle>최근 실행</CardTitle>
              <CardDescription>작업 실행 상태</CardDescription>
              <CardAction>
                <Clock3Icon className="text-muted-foreground" />
              </CardAction>
            </CardHeader>
            <CardContent>
              {summary.isLoading ? (
                <Skeleton className="h-56 w-full" />
              ) : (
                <RunsTable
                  runs={recentRuns}
                  selectedRunId={effectiveSelectedRunId}
                  onSelectRun={setSelectedRunId}
                />
              )}
            </CardContent>
          </Card>

          <RunDetailCard
            key={effectiveSelectedRunId ?? "none"}
            runId={effectiveSelectedRunId}
          />
        </section>

        <Card>
          <CardHeader>
            <CardTitle>코드 위치</CardTitle>
            <CardDescription>에셋 그룹과 코드 레벨 이름</CardDescription>
            <CardAction>
              <GitBranchIcon className="text-muted-foreground" />
            </CardAction>
          </CardHeader>
          <CardContent>
            {summary.isLoading ? (
              <Skeleton className="h-72 w-full" />
            ) : (
              <RepositoryList
                repositories={data?.repositories ?? []}
                onSelectRun={setSelectedRunId}
              />
            )}
          </CardContent>
        </Card>
      </div>
    </AdminShell>
  );
}
