import {
  KNOWN_MAKI_NAMES,
  PALETTE,
  resolveMarkerColor,
  resolveMarkerLabel,
  type PaletteCode,
} from "@kor-travel-map/map-marker-react";
import type { CSSProperties } from "react";

export const FEATURE_KIND_OPTIONS = [
  { value: "place", label: "장소" },
  { value: "event", label: "행사" },
] as const;

export const FEATURE_STATUS_OPTIONS = [
  { value: "draft", label: "초안" },
  { value: "active", label: "사용 중" },
  { value: "inactive", label: "사용 안 함" },
  { value: "hidden", label: "숨김" },
] as const;

export const FEATURE_CHANGE_ACTION_OPTIONS = [
  { value: "add", label: "새로 추가" },
  { value: "update", label: "기존 Feature 수정" },
  { value: "delete", label: "기존 Feature 삭제" },
] as const;

export const EVENT_STATUS_OPTIONS = [
  { value: "", label: "선택 안 함" },
  { value: "scheduled", label: "예정" },
  { value: "ongoing", label: "진행 중" },
  { value: "ended", label: "종료" },
  { value: "unknown", label: "알 수 없음" },
] as const;

export const PLACE_KIND_OPTIONS = [
  { value: "", label: "선택 안 함" },
  { value: "place", label: "일반 장소" },
  { value: "tourist_attraction", label: "관광지" },
  { value: "restaurant", label: "음식점" },
  { value: "cafe", label: "카페" },
  { value: "lodging", label: "숙박" },
  { value: "hotel", label: "호텔" },
  { value: "museum", label: "박물관/미술관" },
  { value: "park", label: "공원" },
  { value: "festival_venue", label: "행사 장소" },
  { value: "heritage", label: "문화유산" },
  { value: "beach", label: "해수욕장" },
  { value: "trail", label: "둘레길/트레킹" },
  { value: "rest_area", label: "휴게소" },
  { value: "gas_station", label: "주유소" },
  { value: "parking", label: "주차장" },
  { value: "hospital", label: "병원" },
  { value: "pharmacy", label: "약국" },
  { value: "toilet", label: "화장실" },
  { value: "offline_upload", label: "오프라인 업로드" },
  { value: "unknown", label: "알 수 없음" },
] as const;

const MARKER_COLOR_NAMES: Record<PaletteCode, string> = {
  "P-01": "파랑",
  "P-02": "주황",
  "P-03": "초록",
  "P-04": "빨강",
  "P-05": "보라",
  "P-06": "갈색",
  "P-07": "분홍",
  "P-08": "회색",
  "P-09": "올리브",
  "P-10": "하늘",
  "P-11": "노랑",
  "P-12": "에메랄드",
  "P-13": "남색",
  "P-14": "장미",
  "P-15": "청록",
  "P-16": "바이올렛",
};

export const MARKER_ICON_OPTIONS = [...KNOWN_MAKI_NAMES].sort((left, right) =>
  left.localeCompare(right),
);

export const MARKER_COLOR_OPTIONS = (
  Object.entries(PALETTE) as Array<[PaletteCode, string]>
).map(([code, hex]) => ({
  code,
  hex,
  label: `${MARKER_COLOR_NAMES[code]} · ${code} · ${hex}`,
}));

export function withCurrentOption(
  options: readonly { value: string; label: string }[],
  value: string,
  fallbackLabel = "현재 값",
) {
  const current = value.trim();
  if (current.length === 0 || options.some((option) => option.value === current)) {
    return options;
  }
  return [{ value: current, label: `${fallbackLabel}: ${current}` }, ...options];
}

export function markerIconLabel(value: string): string {
  return `${resolveMarkerLabel(value)} · ${value}`;
}

export function readableTextColor(hexColor: string): "#111827" | "#ffffff" {
  const normalized = hexColor.replace("#", "");
  if (normalized.length !== 6) return "#111827";
  const red = Number.parseInt(normalized.slice(0, 2), 16);
  const green = Number.parseInt(normalized.slice(2, 4), 16);
  const blue = Number.parseInt(normalized.slice(4, 6), 16);
  const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;
  return luminance > 0.62 ? "#111827" : "#ffffff";
}

export function markerColorSelectStyle(markerColor: string): CSSProperties {
  const backgroundColor = resolveMarkerColor(markerColor);
  return {
    backgroundColor,
    color: readableTextColor(backgroundColor),
  };
}
