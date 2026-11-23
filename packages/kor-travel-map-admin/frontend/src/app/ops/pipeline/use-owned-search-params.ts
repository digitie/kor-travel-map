"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * 화면이 소유하는 URL query 상태.
 *
 * Next는 same-route `history.pushState/replaceState`를 **transition**으로 router 상태
 * (`useSearchParams`)에 옮긴다. 그래서 `searchParams`는 방금 쓴 URL보다 늦고, 이어진 쓰기들이
 * 따로따로·늦게 commit되며, 늦은 commit은 그 시점의 canonical URL을 브라우저에 다시 써서
 * `window.location`까지 잠깐 되돌린다. 필터 입력을 빠르게 이어 치면(상태 → provider dataset ID
 * → sync scope) 그 낡은 값을 기준으로 다음 URL을 만들거나 입력 칸을 다시 그려, 앞 입력이 빠지고
 * 뒤 입력이 사라졌다(`ops-pipeline.spec.ts` "필터가 executions 쿼리 파라미터로 전달된다"의
 * 간헐 실패 — n150 stress 실측에서 scope가 한 번도 요청에 실리지 않았다).
 *
 * 여기서는 화면이 쓴 query를 **같은 렌더에서** 상태로 들고, router commit은 우리 쓰기의 반영
 * (중간 상태 포함)이면 무시하고, 우리가 쓴 적 없는 commit만 외부 이동(Back/Forward·Link·다른
 * 코드의 history 변경)으로 받아들인다.
 */
export interface OwnedQueryState {
  /** 마지막으로 본 router commit의 query. */
  committed: string;
  /** 화면이 읽는 query — 우리 쓰기는 즉시, 외부 이동은 commit 때 반영된다. */
  query: string;
  /** 아직 다 반영되지 않은 우리 쓰기(쓴 순서). 마지막 쓰기가 commit되면 비운다. */
  writes: string[];
}

export function reconcileCommittedQuery(
  state: OwnedQueryState,
  committed: string,
): OwnedQueryState {
  if (committed === state.committed) {
    return state;
  }
  if (state.writes.length > 0 && committed === state.writes.at(-1)) {
    return { committed, query: state.query, writes: [] };
  }
  if (state.writes.includes(committed)) {
    // 우리 앞선 쓰기의 늦은(또는 순서가 뒤바뀐) commit — 화면 상태를 되돌리지 않는다.
    return { ...state, committed };
  }
  return { committed, query: committed, writes: [] };
}

export function recordOwnedWrite(
  state: OwnedQueryState,
  query: string,
): OwnedQueryState {
  return { ...state, query, writes: [...state.writes, query] };
}

export type UrlUpdates = Record<string, string | null>;

/** 갱신을 적용한 `next`를 규칙에 맞게 고친다(`previous`는 갱신 전). */
export type NormalizeQuery = (
  previous: URLSearchParams,
  next: URLSearchParams,
  updates: UrlUpdates,
) => void;

export function useOwnedSearchParams(normalize: NormalizeQuery): {
  searchParams: URLSearchParams;
  updateUrl: (updates: UrlUpdates, mode?: "push" | "replace") => void;
} {
  const pathname = usePathname();
  const committed = useSearchParams().toString();
  const [stored, setStored] = useState<OwnedQueryState>(() => ({
    committed,
    query: committed,
    writes: [],
  }));
  const state = reconcileCommittedQuery(stored, committed);
  if (state !== stored) {
    setStored(state);
  }
  // 한 이벤트 안에서 여러 번 쓸 때도 바로 앞 쓰기를 기준으로 삼는다.
  const queryRef = useRef(state.query);
  useEffect(() => {
    queryRef.current = state.query;
  }, [state.query]);

  useEffect(() => {
    // Back/Forward는 우리 쓰기와 무관하다 — 다음 commit을 외부 이동으로 받는다.
    const onPopState = () =>
      setStored((current) => ({ ...current, writes: [] }));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const updateUrl = useCallback(
    (updates: UrlUpdates, mode: "push" | "replace" = "push") => {
      const previous = new URLSearchParams(queryRef.current);
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === "") {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      }
      normalize(previous, next, updates);
      const query = next.toString();
      if (query === previous.toString()) {
        return;
      }
      queryRef.current = query;
      setStored((current) => recordOwnedWrite(current, query));
      window.history[mode === "push" ? "pushState" : "replaceState"](
        null,
        "",
        query ? `${pathname}?${query}` : pathname,
      );
    },
    [normalize, pathname],
  );

  const searchParams = useMemo(
    () => new URLSearchParams(state.query),
    [state.query],
  );
  return { searchParams, updateUrl };
}
