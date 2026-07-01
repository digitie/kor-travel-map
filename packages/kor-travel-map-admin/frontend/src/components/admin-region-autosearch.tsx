"use client";

import { ChevronDownIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  korTravelGeoCodesFromCandidate,
  searchDistricts,
  type KorTravelGeoCandidate,
} from "@/api/korTravelGeo";
import { Badge } from "@/components/ui/badge";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type RegionCodeKind = "sido" | "sigungu" | "legal_dong" | "admin_dong";

interface AdminRegionAutoSearchProps {
  className?: string;
  id: string;
  kind: RegionCodeKind;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSelectCandidate?: (candidate: KorTravelGeoCandidate) => void;
  placeholder?: string;
}

const SIDO_SEARCH_LABEL_BY_CODE: Record<string, string> = {
  "11": "서울특별시",
  "26": "부산광역시",
  "27": "대구광역시",
  "28": "인천광역시",
  "29": "광주광역시",
  "30": "대전광역시",
  "31": "울산광역시",
  "36": "세종특별자치시",
  "41": "경기도",
  "42": "강원특별자치도",
  "43": "충청북도",
  "44": "충청남도",
  "45": "전북특별자치도",
  "46": "전라남도",
  "47": "경상북도",
  "48": "경상남도",
  "50": "제주특별자치도",
  "51": "강원특별자치도",
  "52": "전북특별자치도",
};

const REGION_CODE_META: Record<
  RegionCodeKind,
  { displayName: string; length: number }
> = {
  sido: { displayName: "시도", length: 2 },
  sigungu: { displayName: "시군구", length: 5 },
  legal_dong: { displayName: "법정동", length: 10 },
  admin_dong: { displayName: "행정동", length: 10 },
};

function codeFromCandidate(
  candidate: KorTravelGeoCandidate,
  kind: RegionCodeKind,
): string | undefined {
  const codes = korTravelGeoCodesFromCandidate(candidate);
  if (kind === "sido") return codes.sido_code;
  if (kind === "sigungu") return codes.sigungu_code;
  if (kind === "legal_dong") return codes.legal_dong_code;
  return codes.admin_dong_code;
}

function candidateKey(candidate: KorTravelGeoCandidate): string {
  return [
    candidate.match_kind,
    candidate.region?.sido,
    candidate.region?.sigungu,
    candidate.region?.bjd_cd,
    candidate.region?.legal_dong,
    candidate.region?.admin_dong,
    candidate.address?.legal_dong_code,
    candidate.address?.admin_dong_code,
  ]
    .map((item) => String(item ?? ""))
    .join("|");
}

function regionLabel(
  candidate: KorTravelGeoCandidate,
  kind: RegionCodeKind,
): string {
  const region = candidate.region;
  const address = candidate.address;
  const parts =
    kind === "sido"
      ? [region?.sido]
      : kind === "sigungu"
        ? [region?.sido, region?.sigungu]
        : kind === "legal_dong"
          ? [
              region?.sido,
              region?.sigungu,
              region?.legal_dong ?? region?.eup_myeon_dong,
            ]
          : [
              region?.sido,
              region?.sigungu,
              region?.admin_dong ?? region?.eup_myeon_dong,
            ];
  const regionName = parts
    .map((item) => item?.trim())
    .filter((item): item is string => Boolean(item))
    .join(" ");
  return (
    regionName ||
    address?.parcel_address ||
    address?.road_address ||
    address?.full ||
    candidate.match_kind ||
    "검색 결과"
  );
}

function resultDescription(
  candidate: KorTravelGeoCandidate,
  kind: RegionCodeKind,
  code: string,
): string {
  const codes = korTravelGeoCodesFromCandidate(candidate);
  const meta = REGION_CODE_META[kind];
  const parent =
    kind === "sido"
      ? null
      : kind === "sigungu"
        ? codes.sido_code
        : codes.sigungu_code;
  return parent
    ? `${meta.displayName} ${code} · 상위 ${parent}`
    : `${meta.displayName} ${code}`;
}

function codeValidationMessage(
  value: string,
  kind: RegionCodeKind,
): string | null {
  const raw = value.trim();
  if (raw.length === 0) return null;
  const meta = REGION_CODE_META[kind];
  if (!/^\d+$/.test(raw)) {
    return `${meta.displayName} 코드는 ${meta.length}자리 숫자여야 합니다. 검색 결과에서 선택하세요.`;
  }
  if (raw.length !== meta.length) {
    return `${meta.displayName} 코드는 ${meta.length}자리여야 합니다.`;
  }
  return null;
}

function matchesNumericQuery(raw: string, code: string): boolean {
  if (!/^\d+$/.test(raw)) return true;
  if (raw.length <= code.length) return code.startsWith(raw);
  return raw.startsWith(code);
}

async function searchRegionCandidates(
  rawValue: string,
): Promise<KorTravelGeoCandidate[]> {
  const raw = rawValue.trim();
  if (raw.length === 0) return [];
  if (/^\d+$/.test(raw)) {
    if (raw.length < 2) return [];
    const sidoCode = raw.slice(0, 2);
    const sidoQuery = SIDO_SEARCH_LABEL_BY_CODE[sidoCode];
    if (!sidoQuery) return [];
    const response = await searchDistricts(sidoQuery, {
      sigCd: raw.length >= 5 ? raw.slice(0, 5) : sidoCode,
      size: 100,
    });
    return response.candidates;
  }
  const response = await searchDistricts(raw, { size: 30 });
  return response.candidates;
}

interface VisibleRegionCandidate {
  candidate: KorTravelGeoCandidate;
  code: string;
  key: string;
  label: string;
}

function AdminRegionAutoSearch({
  className,
  id,
  kind,
  label,
  value,
  onChange,
  onSelectCandidate,
  placeholder = "시군구 또는 읍면동 검색",
}: AdminRegionAutoSearchProps) {
  const query = value.trim();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<KorTravelGeoCandidate[]>([]);
  const [resultsOpen, setResultsOpen] = useState(false);
  const suppressOpenForQueryRef = useRef<string | null>(null);

  useEffect(() => {
    if (query.length === 0) {
      return;
    }

    let cancelled = false;
    const timeout = window.setTimeout(() => {
      setPending(true);
      setError(null);
      void searchRegionCandidates(query)
        .then((response) => {
          if (cancelled) return;
          setCandidates(response);
          if (suppressOpenForQueryRef.current === query) {
            suppressOpenForQueryRef.current = null;
            setResultsOpen(false);
          } else {
            setResultsOpen(true);
          }
        })
        .catch((searchError: unknown) => {
          if (cancelled) return;
          setCandidates([]);
          setError(
            searchError instanceof Error
              ? searchError.message
              : String(searchError),
          );
        })
        .finally(() => {
          if (!cancelled) {
            setPending(false);
          }
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [query]);

  const visibleCandidates = useMemo<VisibleRegionCandidate[]>(() => {
    if (query.length === 0) return [];
    const seen = new Set<string>();
    const next: VisibleRegionCandidate[] = [];
    for (const candidate of candidates) {
      const code = codeFromCandidate(candidate, kind);
      if (!code || !matchesNumericQuery(query, code)) continue;
      const labelText = regionLabel(candidate, kind);
      const key = `${kind}:${code}:${labelText}:${candidateKey(candidate)}`;
      const dedupeKey = `${code}:${labelText}`;
      if (seen.has(dedupeKey)) continue;
      seen.add(dedupeKey);
      next.push({ candidate, code, key, label: labelText });
      if (next.length >= 8) break;
    }
    return next;
  }, [candidates, kind, query]);
  const visibleError = query.length > 0 ? error : null;
  const visiblePending = query.length > 0 && pending;
  const validationError = codeValidationMessage(value, kind);
  const invalid = Boolean(visibleError || validationError);
  const resultButtonLabel =
    query.length === 0
      ? "검색 결과"
      : visiblePending
        ? "검색 중"
        : `검색 결과 ${visibleCandidates.length}건`;

  return (
    <Field className={className} data-invalid={invalid ? true : undefined}>
      <div className="flex items-center justify-between gap-2">
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
        <Badge variant={visiblePending ? "outline" : "secondary"}>
          {visiblePending ? "검색 중" : `${visibleCandidates.length}건`}
        </Badge>
      </div>
      <Input
        aria-describedby={`${id}-region-results`}
        aria-invalid={visibleError ? true : undefined}
        id={id}
        placeholder={placeholder}
        value={value}
        inputMode="search"
        className={cn(
          /^\d+$/.test(value.trim()) ? "font-mono tracking-[0.18em]" : null,
        )}
        onChange={(event) => {
          const nextValue = event.target.value;
          onChange(nextValue);
          setResultsOpen(nextValue.trim().length > 0);
        }}
      />
      <div className="relative" id={`${id}-region-results`}>
        {query.length > 0 ? (
          <button
            aria-controls={`${id}-region-results-popup`}
            aria-expanded={resultsOpen}
            className="flex w-full items-center justify-between rounded-md border bg-background px-2.5 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted"
            type="button"
            onClick={() => setResultsOpen((current) => !current)}
          >
            <span>{resultButtonLabel}</span>
            <ChevronDownIcon
              aria-hidden="true"
              className={cn(
                "size-3.5 transition-transform",
                resultsOpen ? "rotate-180" : null,
              )}
            />
          </button>
        ) : (
          <FieldDescription className="text-xs">
            검색어를 입력하면 같은 계층의 행정구역만 표시됩니다.
          </FieldDescription>
        )}
        {query.length > 0 && resultsOpen ? (
          <div
            className="absolute z-30 mt-1 w-full rounded-md border bg-popover p-1 shadow-lg"
            id={`${id}-region-results-popup`}
          >
            {visibleCandidates.length > 0 ? (
              <div className="flex max-h-48 flex-col overflow-auto">
                {visibleCandidates.map((item) => (
                  <button
                    className={cn(
                      "rounded-sm px-2 py-1.5 text-left text-sm",
                      "hover:bg-muted focus-visible:bg-muted focus-visible:outline-none",
                      item.code === value.trim()
                        ? "bg-primary/10 text-primary"
                        : null,
                    )}
                    key={item.key}
                    type="button"
                    onClick={() => {
                      suppressOpenForQueryRef.current = item.code;
                      onChange(item.code);
                      onSelectCandidate?.(item.candidate);
                      setResultsOpen(false);
                    }}
                  >
                    <span className="block font-medium">{item.label}</span>
                    <span className="block text-xs text-muted-foreground">
                      {resultDescription(item.candidate, kind, item.code)}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <FieldDescription className="px-2 py-2 text-xs">
                {visiblePending ? "검색 중입니다." : "검색 결과가 없습니다."}
              </FieldDescription>
            )}
          </div>
        ) : null}
      </div>
      {validationError ? <FieldError>{validationError}</FieldError> : null}
      {visibleError ? <FieldError>{visibleError}</FieldError> : null}
    </Field>
  );
}

export { AdminRegionAutoSearch };
