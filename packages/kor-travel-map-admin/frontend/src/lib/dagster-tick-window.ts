/**
 * Map API가 Dagster `ticks`를 읽는 창(`kortravelmap.api.dagster_graphql`의
 * `SCHEDULE_TICK_WINDOW_SECONDS`·`SENSOR_TICK_WINDOW_SECONDS`). 값이 갈리면
 * `tests/unit/test_dagster_tick_window.py`가 빨갛다.
 *
 * 창 밖의 tick은 응답에 없다 — RUNNING인데 `recent_ticks`가 비면 "멈춤"인지 "아직 안 돎"인지
 * 응답만으로는 모른다. 그래서 빈 목록을 "tick 없음"이 아니라 "창 안 tick 없음"으로 표시한다.
 */
export const SCHEDULE_TICK_WINDOW_SECONDS = 2 * 24 * 60 * 60;
export const SENSOR_TICK_WINDOW_SECONDS = 60 * 60;

export const SCHEDULE_TICK_WINDOW_LABEL = "최근 2일 tick 없음";
export const SENSOR_TICK_WINDOW_LABEL = "최근 1시간 tick 없음";

type Tick = { status: string; timestamp: number | null } | null;

/** 첫 tick 또는, RUNNING인데 창 안에 tick이 없으면 그 사실을 상태 칸에 보이는 표지로. */
export function lastTickOrWindowNotice(
  ticks: readonly { status: string; timestamp?: number | null }[] | null | undefined,
  instigatorStatus: string | null | undefined,
  notice: string,
): Tick {
  const first = ticks?.[0];
  if (first) return { status: first.status, timestamp: first.timestamp ?? null };
  return instigatorStatus === "RUNNING" ? { status: notice, timestamp: null } : null;
}
