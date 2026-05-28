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

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from krtour.map_debug_ui.etl_fixtures import (
    FIXTURE_REGISTRY,
    list_datasets,
    list_providers,
    run_fixture_preview,
)
from krtour.map_debug_ui.etl_live import (
    LIVE_LOADER_REGISTRY,
    LiveLoaderError,
    find_live_loader,
)
from krtour.map_debug_ui.settings import DebugUiSettings

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
    live_supported: bool = Field(
        default=False,
        description=(
            "`?source=live` 활성 여부. False면 fixture만 — live 호출은 501. "
            "PR#47부터 KMA 3 dataset 활성."
        ),
    )


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
    """registry에서 provider의 dataset entries 생성. ``live_supported``는
    `etl_live.LIVE_LOADER_REGISTRY`에 매핑 여부로 결정."""
    return [
        _DatasetEntry(
            dataset=e.dataset,
            variant=e.variant,
            description=e.description,
            live_supported=(e.provider, e.dataset) in LIVE_LOADER_REGISTRY,
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
    if source == "live":
        return await _run_live_preview(provider, dataset, request)

    try:
        result = run_fixture_preview(provider, dataset)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return EtlPreviewResponse(**result)


async def _run_live_preview(
    provider: str, dataset: str, request: Request
) -> EtlPreviewResponse:
    """``?source=live`` 분기 — provider 실 호출 + 변환 결과 응답."""
    entry = next(
        (
            e
            for e in FIXTURE_REGISTRY
            if e.provider == provider and e.dataset == dataset
        ),
        None,
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"등록되지 않은 (provider, dataset): ({provider!r}, "
                f"{dataset!r}). `/debug/etl/providers`에서 확인."
            ),
        )
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
    params: dict[str, str] = {
        k: v for k, v in request.query_params.items() if k != "source"
    }

    settings = DebugUiSettings()
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
        provider=entry.provider,
        dataset=entry.dataset,
        source="live",
        variant=entry.variant,
        description=entry.description,
        count=len(items),
        items=items,
    )
