const KST_TIME_ZONE = "Asia/Seoul";
const OPINET_PROVIDER = "python-opinet-api";
const KST_UTC_OFFSET_MS = 9 * 60 * 60 * 1_000;

const kstDateFormatter = new Intl.DateTimeFormat("en-US", {
  day: "numeric",
  month: "numeric",
  timeZone: KST_TIME_ZONE,
  year: "numeric",
});

interface KstDateParts {
  year: number;
  month: number;
  day: number;
}

export interface PriceObservation {
  provider?: string | null;
  observed_at: string;
}

function kstDateParts(value: Date | string): KstDateParts | null {
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) return null;

  const parts = new Map<string, number>();
  for (const part of kstDateFormatter.formatToParts(date)) {
    if (part.type !== "literal") parts.set(part.type, Number(part.value));
  }
  const year = parts.get("year");
  const month = parts.get("month");
  const day = parts.get("day");
  if (year === undefined || month === undefined || day === undefined) return null;
  return { year, month, day };
}

export function isSameKstCalendarDate(left: Date | string, right: Date | string) {
  const leftParts = kstDateParts(left);
  const rightParts = kstDateParts(right);
  return (
    leftParts !== null &&
    rightParts !== null &&
    leftParts.year === rightParts.year &&
    leftParts.month === rightParts.month &&
    leftParts.day === rightParts.day
  );
}

/** 현재 시각부터 다음 KST 자정까지 남은 밀리초. KST는 UTC+9 고정 시간대다. */
export function millisecondsUntilNextKstMidnight(now: Date = new Date()): number {
  const parts = kstDateParts(now);
  if (parts === null) return 24 * 60 * 60 * 1_000;
  const nextMidnightUtc =
    Date.UTC(parts.year, parts.month - 1, parts.day + 1) - KST_UTC_OFFSET_MS;
  return Math.max(1, nextMidnightUtc - now.getTime());
}

/**
 * KST 자정마다 callback을 한 번 실행한다. 호출자가 반환 cleanup을 effect teardown에
 * 연결하면 timer가 남지 않는다. 분 단위 polling이나 React rerender는 만들지 않는다.
 */
export function scheduleKstMidnightTicks(callback: () => void): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  const scheduleNext = () => {
    timer = globalThis.setTimeout(() => {
      if (stopped) return;
      callback();
      scheduleNext();
    }, millisecondsUntilNextKstMidnight());
  };
  scheduleNext();
  return () => {
    stopped = true;
    if (timer !== null) globalThis.clearTimeout(timer);
  };
}

/** OpiNet 관측 중 오늘(KST)이 아닌 값이 있으면 marker용 과거 날짜를 반환한다. */
export function opinetPastPriceLabel(
  points: readonly PriceObservation[],
  now: Date = new Date(),
): string | null {
  const oldPoints: Array<{ point: PriceObservation; date: Date }> = [];
  for (const point of points) {
    if (point.provider !== OPINET_PROVIDER) continue;
    const date = new Date(point.observed_at);
    if (
      Number.isFinite(date.getTime()) &&
      !isSameKstCalendarDate(point.observed_at, now)
    ) {
      oldPoints.push({ point, date });
    }
  }
  oldPoints.sort((left, right) => right.date.getTime() - left.date.getTime());
  const latestOld = oldPoints[0];
  if (!latestOld) return null;
  const parts = kstDateParts(latestOld.date);
  return parts ? `과거 ${parts.month}/${parts.day}` : null;
}
