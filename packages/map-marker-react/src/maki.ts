/**
 * Maki icon name → 표시 글리프(Unicode) 매핑 (ADR-029/043, ADR-026).
 *
 * 본 라이브러리는 마커에 maki 아이콘을 표시할 때 두 단계로 동작한다:
 *   1) 알려진 maki name이면 그 의미에 맞는 Unicode 글리프(혹은 단축어)로 매핑.
 *   2) 모르는 name이면 첫 글자(영문)를 라벨로 사용.
 *
 * 정식 maki SVG sprite(`@mapbox/maki`) 번들 통합은 후속 PR — 본 PR는 의존성
 * 가벼움 우선 + 텍스트/이모지 fallback. 실 SVG는 향후 동일 API로 swap.
 */

/**
 * 알려진 maki icon name → 단일 글리프. provider 변환기가 emit하는 marker_icon
 * (knps/krheritage/datagokr/krex/opinet 등)을 우선 커버한다. 필요 시 후속 PR에서
 * 추가/조정 (안정 API: name → glyph).
 */
const MAKI_GLYPH: Readonly<Record<string, string>> = Object.freeze({
  // 휴게소/주유소 (krex, opinet)
  "fuel": "⛽", // ⛽
  "rest-area": "\u{1F6BB}", // 🚻 (대체)
  "restaurant": "\u{1F374}", // 🍴
  "cafe": "☕", // ☕
  // 자연/공원 (knps/krheritage)
  "park": "\u{1F333}", // 🌳
  "park-alt1": "\u{1F332}", // 🌲
  "natural": "\u{1F33F}", // 🌿
  "mountain": "⛰", // ⛰️
  "campsite": "⛺", // ⛺
  "shelter": "\u{1F3D5}", // 🏕️
  "barrier": "\u{1F6AB}", // 🚫 (입산통제)
  "hazard": "⚠", // ⚠️
  // 국가유산/문화
  "monument": "\u{1F3DB}", // 🏛️
  "religious-buddhist": "\u{1F6D5}", // 🛕
  "religious-christian": "⛪", // ⛪
  "religious-shinto": "⛩", // ⛩️
  // 축제/이벤트 (datagokr)
  "star": "⭐", // ⭐
  "music": "\u{1F3B5}", // 🎵
  "stadium": "\u{1F3DF}", // 🏟️
  // 공지/특보 (kma weather_alerts, krex notices)
  "alert": "⚠", // ⚠️
  "info": "ℹ", // ℹ️
  "construction": "\u{1F6A7}", // 🚧
  // 기타
  "marker": "\u{1F4CD}", // 📍
});

/** 알려진 maki name이면 글리프, 아니면 `null`. */
export function getMakiGlyph(iconName: string | null | undefined): string | null {
  if (!iconName) return null;
  return MAKI_GLYPH[iconName] ?? null;
}

/**
 * marker 라벨 텍스트 — 알려진 maki name이면 글리프, 아니면 영문/한글 첫 글자
 * (라벨이 비어있지 않게 보장). 호출자가 `markerIcon` 미지정 시 `"·"`(·) 등
 * 중립 라벨도 가능.
 */
export function resolveMarkerLabel(
  iconName: string | null | undefined,
  fallback: string = "·", // ·
): string {
  const glyph = getMakiGlyph(iconName);
  if (glyph) return glyph;
  if (iconName && iconName.length > 0) return iconName.charAt(0).toUpperCase();
  return fallback;
}

/** 디버깅/문서용 — 본 모듈이 알고 있는 maki name 목록. */
export const KNOWN_MAKI_NAMES: readonly string[] = Object.freeze(
  Object.keys(MAKI_GLYPH),
);
