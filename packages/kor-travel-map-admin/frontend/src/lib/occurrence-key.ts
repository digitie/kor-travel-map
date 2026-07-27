export interface KeyedOccurrence<T> {
  key: string;
  value: T;
}

/**
 * API 계약에 row ID가 없는 표시 전용 목록에 값 identity별 occurrence를 붙인다.
 * 동일 값은 의미상 구분되지 않지만 React sibling key는 유일해야 하므로, 입력 순서에서
 * 같은 identity가 나타난 횟수만 suffix로 사용한다.
 */
export function withOccurrenceKeys<T>(
  values: readonly T[],
  identity: (value: T) => string,
): KeyedOccurrence<T>[] {
  const occurrenceByIdentity = new Map<string, number>();
  return values.map((value) => {
    const itemIdentity = identity(value);
    const occurrence = (occurrenceByIdentity.get(itemIdentity) ?? 0) + 1;
    occurrenceByIdentity.set(itemIdentity, occurrence);
    return {
      key: JSON.stringify([itemIdentity, occurrence]),
      value,
    };
  });
}
