"""``krtour.map_debug_ui.routers.etl`` — ETL preview (수동 trigger).

본 라우터는 운영자가 디버그 UI에서 provider별 변환 함수의 출력을 **수동으로
확인**할 수 있게 해준다. 적재(DB write)는 아직 없음 — 변환 결과만 JSON으로
응답.

소스 모드:
- ``?source=fixture`` — `etl_fixtures.FIXTURE_REGISTRY`의 hard-coded sample을
  변환 함수에 통과시켜 결과 반환. provider client 의존 X. 본 PR에서 동작.
- ``?source=live`` — 실제 provider client 호출 (`python-kma-api` 등 fetch).
  후속 PR로 wiring. 본 PR은 ``HTTPException 501 NotImplementedError``.

ADR 참조
--------
- ADR-005 + ADR-035 — 운영 범위. 본 라우터는 `/debug/` prefix.
- ADR-006 — provider wrapper 금지. 본 라우터는 본 lib 변환 함수만 호출.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from krtour.map_debug_ui.etl_fixtures import (
    FIXTURE_REGISTRY,
    list_datasets,
    list_providers,
    run_fixture_preview,
)

__all__ = [
    "router",
    "ProvidersResponse",
    "ProviderDatasetsResponse",
    "EtlPreviewResponse",
]


router = APIRouter(prefix="/debug/etl", tags=["debug", "etl"])


# ── 응답 schema ────────────────────────────────────────────────────────


class _DatasetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    variant: str = Field(
        description="`FeatureBundle` / `WeatherValue` / `PriceValue`.",
    )
    description: str


class _ProviderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    datasets: list[_DatasetEntry]


class ProvidersResponse(BaseModel):
    """`/debug/etl/providers` 응답."""

    model_config = ConfigDict(extra="forbid")

    providers: list[_ProviderEntry]


class ProviderDatasetsResponse(BaseModel):
    """`/debug/etl/{provider}/datasets` 응답."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    datasets: list[_DatasetEntry]


class EtlPreviewResponse(BaseModel):
    """`/debug/etl/{provider}/{dataset}/preview` 응답."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset: str
    source: Literal["fixture", "live"]
    variant: str = Field(description="`FeatureBundle` / `WeatherValue` / `PriceValue`.")
    description: str
    count: int
    items: list[dict[str, Any]] = Field(
        description=(
            "변환 결과 list. variant에 따라 schema가 다르다 — FeatureBundle "
            "(feature/source_record/source_link 3-key dict) / WeatherValue / "
            "PriceValue 등."
        ),
    )


# ── helper: build dataset entries ─────────────────────────────────────


def _dataset_entries(provider: str) -> list[_DatasetEntry]:
    """registry에서 provider의 dataset entries 생성."""
    return [
        _DatasetEntry(
            dataset=e.dataset, variant=e.variant, description=e.description
        )
        for e in FIXTURE_REGISTRY
        if e.provider == provider
    ]


# ── 라우터 ───────────────────────────────────────────────────────────


@router.get(
    "/providers",
    response_model=ProvidersResponse,
    summary="ETL preview 가능한 provider + dataset 목록",
    description=(
        "fixture 변환이 등록된 provider/dataset 매트릭스. 추가 변환 함수가 본 "
        "lib에 들어오면 `etl_fixtures.FIXTURE_REGISTRY`에 1행 등록 → 본 응답에 "
        "자동 반영."
    ),
)
async def get_providers() -> ProvidersResponse:
    entries: list[_ProviderEntry] = []
    for provider in list_providers():
        entries.append(
            _ProviderEntry(provider=provider, datasets=_dataset_entries(provider))
        )
    return ProvidersResponse(providers=entries)


@router.get(
    "/{provider}/datasets",
    response_model=ProviderDatasetsResponse,
    summary="특정 provider의 dataset 목록",
)
async def get_provider_datasets(provider: str) -> ProviderDatasetsResponse:
    datasets = list_datasets(provider)
    if not datasets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"등록된 provider 아님: {provider!r}. "
                f"`/debug/etl/providers`에서 확인."
            ),
        )
    return ProviderDatasetsResponse(
        provider=provider, datasets=_dataset_entries(provider)
    )


@router.post(
    "/{provider}/{dataset}/preview",
    response_model=EtlPreviewResponse,
    summary="provider 변환 함수 dry-run preview",
    description=(
        "fixture 또는 live source로 provider raw → DTO 변환을 실행하고 결과를 "
        "JSON으로 응답. DB write 없음. fixture 모드는 외부 의존 X — 본 lib "
        "변환 함수 동작 검증용. live 모드는 후속 PR로."
    ),
    responses={
        404: {"description": "등록되지 않은 (provider, dataset) 조합"},
        501: {"description": "source=live 미구현 (후속 PR)"},
    },
)
async def post_preview(
    provider: str,
    dataset: str,
    source: Literal["fixture", "live"] = Query(default="fixture"),
) -> EtlPreviewResponse:
    if source == "live":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "source=live 미구현. 본 PR(#44)은 fixture 모드만. "
                "실 provider client 호출은 후속 PR에서 wiring "
                "(provider 라이브러리 의존성 추가 + .env 키 입력 절차 동반)."
            ),
        )

    try:
        result = run_fixture_preview(provider, dataset)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return EtlPreviewResponse(**result)
