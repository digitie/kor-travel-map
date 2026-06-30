"use client";

import { useEffect, useMemo, useState } from "react";

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

type RegionCodeKind = "sigungu" | "legal_dong" | "admin_dong";

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

function codeFromCandidate(
  candidate: KorTravelGeoCandidate,
  kind: RegionCodeKind,
): string | undefined {
  const codes = korTravelGeoCodesFromCandidate(candidate);
  if (kind === "sigungu") return codes.sigungu_code;
  if (kind === "legal_dong") return codes.legal_dong_code;
  return codes.admin_dong_code;
}

function candidateKey(candidate: KorTravelGeoCandidate): string {
  return [
    candidate.match_kind,
    candidate.region?.sig_cd,
    candidate.region?.bjd_cd,
    candidate.address?.legal_dong_code,
    candidate.address?.admin_dong_code,
    candidate.address?.road_address,
    candidate.address?.parcel_address,
  ]
    .map((item) => String(item ?? ""))
    .join("|");
}

function regionLabel(candidate: KorTravelGeoCandidate): string {
  const region = candidate.region;
  const address = candidate.address;
  const regionName = [
    region?.sido,
    region?.sigungu,
    region?.eup_myeon_dong ?? region?.legal_dong ?? region?.admin_dong,
  ]
    .map((item) => item?.trim())
    .filter(Boolean)
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

function resultDescription(candidate: KorTravelGeoCandidate): string {
  const codes = korTravelGeoCodesFromCandidate(candidate);
  const parts = [
    codes.sigungu_code ? `시군구 ${codes.sigungu_code}` : null,
    codes.legal_dong_code ? `법정동 ${codes.legal_dong_code}` : null,
    codes.admin_dong_code ? `행정동 ${codes.admin_dong_code}` : null,
  ].filter(Boolean);
  return parts.join(" · ") || "코드 없음";
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

  const visibleCandidates = useMemo(
    () =>
      query.length === 0
        ? []
        : candidates
            .filter((candidate) => codeFromCandidate(candidate, kind))
            .slice(0, 8),
    [candidates, kind, query.length],
  );
  const visibleError = query.length > 0 ? error : null;
  const visiblePending = query.length > 0 && pending;

  return (
    <Field className={className} data-invalid={visibleError ? true : undefined}>
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
        onChange={(event) => onChange(event.target.value)}
      />
      <div
        className="rounded-md border bg-background"
        id={`${id}-region-results`}
      >
        {visibleCandidates.length > 0 ? (
          <div className="flex max-h-44 flex-col overflow-auto p-1">
            {visibleCandidates.map((candidate) => {
              const nextValue = codeFromCandidate(candidate, kind);
              if (!nextValue) return null;
              return (
                <button
                  className={cn(
                    "rounded-sm px-2 py-1.5 text-left text-sm",
                    "hover:bg-muted focus-visible:bg-muted focus-visible:outline-none",
                  )}
                  key={candidateKey(candidate)}
                  type="button"
                  onClick={() => {
                    onChange(nextValue);
                    onSelectCandidate?.(candidate);
                  }}
                >
                  <span className="block font-medium">{regionLabel(candidate)}</span>
                  <span className="block text-xs text-muted-foreground">
                    {resultDescription(candidate)}
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <FieldDescription className="px-2 py-2 text-xs">
            {query.length === 0
              ? "검색어를 입력하면 결과가 표시됩니다."
              : visiblePending
                ? "검색 중입니다."
                : "검색 결과가 없습니다."}
          </FieldDescription>
        )}
      </div>
      {visibleError ? <FieldError>{visibleError}</FieldError> : null}
    </Field>
  );
}

export { AdminRegionAutoSearch };
