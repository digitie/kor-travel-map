"""``test_load_enrichment_links`` — enrichment source_record/link 적재 (T-RV-52b-2).

``load_source_record_links`` 카운팅 로직과 ``EnrichmentLoadResult.merge``를 mock
upsert로 DB 없이 검증한다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import krtour.map.infra.feature_repo as feature_repo
from krtour.map.infra.feature_repo import EnrichmentLoadResult


@pytest.mark.unit
def test_enrichment_load_result_merge() -> None:
    a = EnrichmentLoadResult(
        enrichments_total=1, source_records_inserted=1, source_links_inserted=1
    )
    b = EnrichmentLoadResult(
        enrichments_total=2,
        source_records_inserted=1,
        source_links_inserted=0,
        source_links_updated=2,
    )
    merged = a.merge(b)
    assert merged.enrichments_total == 3
    assert merged.source_records_inserted == 2
    assert merged.source_links_inserted == 1
    assert merged.source_links_updated == 2


@pytest.mark.unit
def test_load_source_record_links_counts_inserts_and_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # upsert_*는 "new" record/link만 신규(insert=True)로 본다.
    async def _fake_record(session: Any, record: Any) -> bool:
        return record == "new"

    async def _fake_link(session: Any, link: Any) -> bool:
        return link == "new"

    monkeypatch.setattr(feature_repo, "upsert_source_record", _fake_record)
    monkeypatch.setattr(feature_repo, "upsert_source_link", _fake_link)

    pairs = [("new", "new"), ("old", "old"), ("new", "old")]
    result = asyncio.run(
        feature_repo.load_source_record_links(None, pairs)  # type: ignore[arg-type]
    )

    assert result.enrichments_total == 3
    # source_record 신규 2건("new" 2회), source_link 신규 1건("new" 1회).
    assert result.source_records_inserted == 2
    assert result.source_links_inserted == 1
    # link 갱신 2건("old" 2회).
    assert result.source_links_updated == 2


@pytest.mark.unit
def test_load_source_record_links_empty() -> None:
    result = asyncio.run(feature_repo.load_source_record_links(None, []))  # type: ignore[arg-type]
    assert result.enrichments_total == 0
    assert result.source_records_inserted == 0
