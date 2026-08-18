// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
/**
 * 상태 어휘 잠금 테스트 — design.md §Status colour semantics의 두 규약을 회귀로 막는다.
 * 1. 라벨 → tone 은 함수다: 같은 한글 라벨이 서로 다른 tone 을 갖지 않는다. 한 화면에 두 축의
 *    배지가 같이 뜨면 같은 글자가 다른 색으로 보여 색의 의미가 무너지기 때문이다.
 * 2. 라벨 사전과 tone 테이블의 키 집합이 같다: 둘 중 하나만 적으면 배지가 라벨 없이 색만,
 *    또는 색 없이 라벨만 갖게 된다.
 */
import { describe, expect, it } from "vitest";

import {
  STATUS_LABELS,
  STATUS_TONE,
  normalizeStatusKey,
  statusLabel,
  toneFor,
} from "./status-label";

describe("status 어휘 정본", () => {
  it("같은 한글 라벨은 같은 tone만 갖는다", () => {
    const tonesByLabel = new Map<string, Map<string, string[]>>();
    for (const [key, label] of Object.entries(STATUS_LABELS)) {
      const tone = STATUS_TONE[key] ?? "(tone 없음)";
      const byTone = tonesByLabel.get(label) ?? new Map<string, string[]>();
      byTone.set(tone, [...(byTone.get(tone) ?? []), key]);
      tonesByLabel.set(label, byTone);
    }

    const conflicts = [...tonesByLabel]
      .filter(([, byTone]) => byTone.size > 1)
      .map(
        ([label, byTone]) =>
          `"${label}" → ${[...byTone]
            .map(([tone, keys]) => `${tone}(${keys.join(", ")})`)
            .join(" vs ")}`,
      );

    expect(conflicts).toEqual([]);
  });

  it("라벨 사전과 tone 테이블은 같은 키를 덮는다", () => {
    expect(Object.keys(STATUS_LABELS).filter((key) => !(key in STATUS_TONE))).toEqual([]);
    expect(Object.keys(STATUS_TONE).filter((key) => !(key in STATUS_LABELS))).toEqual([]);
  });

  it("모든 키가 정규화된 형태로 보관된다", () => {
    const unnormalized = Object.keys(STATUS_LABELS).filter(
      (key) => normalizeStatusKey(key) !== key,
    );
    expect(unnormalized).toEqual([]);
  });

  it("좁혀 놓은 라벨 세 쌍이 유지된다", () => {
    // design.md §Status: 충돌 시 tone 이 아니라 라벨을 좁힌다.
    expect(statusLabel("pending")).toBe("대기");
    expect(statusLabel("queued")).toBe("실행 대기");
    expect(statusLabel("in_progress")).toBe("진행중");
    expect(statusLabel("ongoing")).toBe("행사중");
    expect(statusLabel("acknowledged")).toBe("확인됨");
    expect(statusLabel("confirmed")).toBe("확인 완료");
  });

  it("정상 취소는 실패가 아니라 중립이다", () => {
    // 빨간 배지면 cancel_failed(취소가 실패한 destructive)와 구분이 사라진다.
    expect(toneFor("cancelled")).toBe("neutral");
    expect(toneFor("canceled")).toBe("neutral");
    expect(toneFor("cancel-failed")).toBe("destructive");
  });
});
