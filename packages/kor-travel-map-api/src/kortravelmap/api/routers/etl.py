"""``kortravelmap.api.routers.etl`` — ETL preview (수동 trigger).

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

from time import perf_counter
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from kortravelmap.api.etl_fixtures import (
    FIXTURE_REGISTRY,
    run_fixture_preview,
)
from kortravelmap.api.etl_live import (
    LIVE_LOADER_REGISTRY,
    LiveLoaderError,
    find_live_loader,
)
from kortravelmap.api.provider_catalog import (
    ProviderDatasetCatalogEntry,
    catalog_datasets,
    find_catalog_entry,
    list_catalog_providers,
)
from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.settings import ApiSettings

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
        description=(
            "`FeatureBundle` / `WeatherValue` / `PriceValue`. fixture 미등록 "
            "dataset은 카탈로그 feature_kind 기반 추정값."
        ),
    )
    description: str
    feature_kind: str = Field(
        description="산출 Feature 종류 (place/event/notice/price/weather/route/area).",
    )
    is_feature_load: bool = Field(
        description="새 Feature(FeatureBundle) 적재 여부 (WeatherValue/PriceValue는 False).",
    )
    live_supported: bool = Field(
        default=False,
        description=(
            "`?source=live` 활성 여부. False면 fixture만 — live 호출은 501. "
            "PR#47부터 KMA 3 dataset 활성."
        ),
    )
    preview: str = Field(
        default="none",
        description=(
            "ETL preview 가용성 — `fixture`(오프라인 replay) / `live`(provider "
            "실호출) / `none`(미배선). `none`이면 preview는 'no preview fixture "
            "(use live)' 안내(404)로 응답."
        ),
    )


class _ProviderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    datasets: list[_DatasetEntry]


class ProvidersData(BaseModel):
    """`/debug/etl/providers` data payload."""

    model_config = ConfigDict(extra="forbid")

    providers: list[_ProviderEntry]


class ProvidersResponse(BaseModel):
    """`/debug/etl/providers` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ProvidersData
    meta: Meta


class ProviderDatasetsData(BaseModel):
    """`/debug/etl/{provider}/datasets` data payload."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    datasets: list[_DatasetEntry]


class ProviderDatasetsResponse(BaseModel):
    """`/debug/etl/{provider}/datasets` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ProviderDatasetsData
    meta: Meta


class EtlPreviewData(BaseModel):
    """`/debug/etl/{provider}/{dataset}/preview` data payload."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset: str
    source: Literal["fixture", "live"]
    variant: str = Field(description="`FeatureBundle` / `WeatherValue` / `PriceValue`.")
    description: str
    items: list[dict[str, Any]] = Field(
        description=(
            "변환 결과 list. variant에 따라 schema가 다르다 — FeatureBundle "
            "(feature/source_record/source_link 3-key dict) / WeatherValue / "
            "PriceValue 등."
        ),
    )


class EtlPreviewResponse(BaseModel):
    """`/debug/etl/{provider}/{dataset}/preview` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: EtlPreviewData
    meta: Meta


# ── helper: build dataset entries ─────────────────────────────────────


# fixture variant는 FeatureBundle/WeatherValue/PriceValue 3종. fixture 미등록
# dataset은 catalog의 is_feature_load/feature_kind로 variant를 추정한다 — feature
# load면 FeatureBundle, price kind면 PriceValue, weather kind면 WeatherValue.
def _variant_for(entry: ProviderDatasetCatalogEntry) -> str:
    if entry.is_feature_load:
        return "FeatureBundle"
    if entry.feature_kind == "price":
        return "PriceValue"
    if entry.feature_kind == "weather":
        return "WeatherValue"
    return "Enrichment"


def _dataset_entries(provider: str) -> list[_DatasetEntry]:
    """카탈로그에서 provider의 dataset entries 생성.

    ``preview``는 카탈로그 항목(fixture/live registry 조회)에서, ``variant``/
    ``description``은 fixture 등록 시 그 메타를, 아니면 카탈로그 라벨/추정 variant를
    쓴다. ``live_supported``는 `etl_live.LIVE_LOADER_REGISTRY` 매핑 여부.
    """
    fixture_by_key = {(e.provider, e.dataset): e for e in FIXTURE_REGISTRY}
    entries: list[_DatasetEntry] = []
    for entry in catalog_datasets(provider):
        fixture = fixture_by_key.get((entry.provider, entry.dataset_key))
        entries.append(
            _DatasetEntry(
                dataset=entry.dataset_key,
                variant=fixture.variant if fixture else _variant_for(entry),
                description=fixture.description if fixture else entry.label,
                feature_kind=entry.feature_kind,
                is_feature_load=entry.is_feature_load,
                live_supported=((entry.provider, entry.dataset_key) in LIVE_LOADER_REGISTRY),
                preview=entry.preview,
            )
        )
    return entries


# ── 라우터 ───────────────────────────────────────────────────────────


@router.get(
    "/providers",
    response_model=ProvidersResponse,
    summary="ETL 카탈로그 provider + dataset 목록",
    description=(
        "시스템이 ETL 하는 **전 provider×dataset 카탈로그**(`provider_catalog."
        "PROVIDER_DATASET_CATALOG`). fixture 등록 여부와 무관하게 mois/knps/"
        "krheritage/mcst 등 모든 provider가 나온다. 각 dataset의 `preview` 필드"
        "(`fixture`/`live`/`none`)로 preview 가용성을 확인할 수 있다."
    ),
)
async def get_providers() -> ProvidersResponse:
    started_at = perf_counter()
    entries = [
        _ProviderEntry(provider=provider, datasets=_dataset_entries(provider))
        for provider in list_catalog_providers()
    ]
    return ProvidersResponse(
        data=ProvidersData(providers=entries),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/{provider}/datasets",
    response_model=ProviderDatasetsResponse,
    summary="특정 provider의 dataset 목록",
)
async def get_provider_datasets(provider: str) -> ProviderDatasetsResponse:
    started_at = perf_counter()
    datasets = _dataset_entries(provider)
    if not datasets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"등록된 provider 아님: {provider!r}. `/debug/etl/providers`에서 확인."),
        )
    return ProviderDatasetsResponse(
        data=ProviderDatasetsData(provider=provider, datasets=datasets),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/{provider}/{dataset}/preview",
    response_model=EtlPreviewResponse,
    summary="provider 변환 함수 dry-run preview",
    description=(
        "fixture 또는 live source로 provider raw → DTO 변환을 실행하고 결과를 "
        "JSON으로 응답. DB write 없음. fixture 모드는 외부 의존 X. live 모드는 "
        "`etl_live.LIVE_LOADER_REGISTRY` 등록된 dataset만 — `?source=fixture` "
        "응답의 `live_supported` 필드로 확인."
    ),
    responses={
        404: {"description": "등록되지 않은 (provider, dataset) 조합"},
        501: {"description": "source=live 미구현 (LIVE_LOADER_REGISTRY 미등록)"},
        502: {"description": "provider 외부 API 호출 실패"},
        503: {"description": "API key 미설정 (.env 확인)"},
    },
)
async def post_preview(
    request: Request,
    provider: str,
    dataset: str,
    source: Literal["fixture", "live"] = Query(default="fixture"),
) -> EtlPreviewResponse:
    started_at = perf_counter()
    if source == "live":
        return await _run_live_preview(provider, dataset, request, started_at=started_at)

    try:
        result = await run_fixture_preview(provider, dataset)
    except KeyError as exc:
        # fixture 미등록 — 카탈로그에 있으면 "use live", 없으면 unknown.
        catalog_entry = find_catalog_entry(provider, dataset)
        if catalog_entry is not None:
            live_hint = (
                "`?source=live`로 실호출 preview 가능."
                if catalog_entry.preview == "live"
                else "live loader도 미배선 — preview 불가."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"no preview fixture (use live): ({provider!r}, "
                    f"{dataset!r})는 카탈로그에 있으나 fixture 미등록. "
                    f"{live_hint}"
                ),
            ) from exc
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    result.pop("count", None)
    return EtlPreviewResponse(
        data=EtlPreviewData(**result),
        meta=make_meta(started_at=started_at),
    )


async def _run_live_preview(
    provider: str,
    dataset: str,
    request: Request,
    *,
    started_at: float,
) -> EtlPreviewResponse:
    """``?source=live`` 분기 — provider 실 호출 + 변환 결과 응답.

    카탈로그에 있는 (provider, dataset)이면 fixture 미등록이어도 live preview를
    허용한다 — variant/description은 fixture가 있으면 그 메타를, 없으면 카탈로그
    기반 추정/라벨을 쓴다.
    """
    catalog_entry = find_catalog_entry(provider, dataset)
    if catalog_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"등록되지 않은 (provider, dataset): ({provider!r}, "
                f"{dataset!r}). `/debug/etl/providers`에서 확인."
            ),
        )
    fixture = next(
        (e for e in FIXTURE_REGISTRY if e.provider == provider and e.dataset == dataset),
        None,
    )
    variant = fixture.variant if fixture else _variant_for(catalog_entry)
    description = fixture.description if fixture else catalog_entry.label
    loader = find_live_loader(provider, dataset)
    if loader is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"source=live 미구현: ({provider!r}, {dataset!r}). "
                "fixture 모드는 동작하나 live 호출 wiring은 후속 PR. "
                "`etl_live.LIVE_LOADER_REGISTRY`에 매핑 추가 필요."
            ),
        )

    # query 파라미터를 그대로 loader에 전달 (provider별 의미는 loader 자체에서).
    params: dict[str, str] = {k: v for k, v in request.query_params.items() if k != "source"}

    settings = ApiSettings()
    try:
        items = await loader(settings, params)
    except LiveLoaderError as exc:
        # API key 미설정 / provider 응답 실패 등.
        msg = str(exc)
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "미설정" in msg or "not configured" in msg.lower()
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=status_code, detail=msg) from exc

    return EtlPreviewResponse(
        data=EtlPreviewData(
            provider=provider,
            dataset=dataset,
            source="live",
            variant=variant,
            description=description,
            items=items,
        ),
        meta=make_meta(started_at=started_at),
    )
