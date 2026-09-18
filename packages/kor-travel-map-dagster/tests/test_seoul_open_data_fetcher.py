"""서울 열린데이터광장 fetcher — 이 포털 특유의 실패 모양을 센다.

2026-09-18 prod: 서울 책방의 원천인 data.go.kr odcloud 자동변환 API가
**404 `등록되지 않은 서비스 입니다`**로 사라졌다. 날조한 데이터셋 번호와 같은
응답이고 swagger 네임스페이스도 404라, 활용신청으로 되살릴 수 있는 종류가
아니었다. 원천을 서울 열린데이터광장 OA-21062(``TbSlibBookstoreInfo``)로 옮긴다.

이 포털은 **오류도 HTTP 200으로 준다.** 게다가 ``json``을 요청해도 인증 실패는
XML로 온다(2026-09-19 실측). 상태 코드나 파싱 성공으로 판정하면 조용히 0건이
되므로, 여기서 세는 것은 "본문의 ``RESULT.CODE``를 실제로 보는가"다.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest
from kortravelmap.dagster import provider_fetchers
from kortravelmap.dagster.provider_fetchers import (
    _SEOUL_BOOKSTORE_DECLARED_ROWS,
    _SEOUL_OPEN_DATA_MAX_PAGES,
    _SEOUL_OPEN_DATA_PAGE_SIZE,
    ProviderCredentialMissing,
    SeoulOpenDataError,
    fetch_datagokr_file_data_records,
    fetch_seoul_open_data_bookstores,
)
from kortravelmap.dagster.provider_pagination import ProviderPaginationOverrun

_SERVICE = "TbSlibBookstoreInfo"


class _FakeResponse:
    def __init__(self, payload: Any, *, json_ok: bool = True) -> None:
        self._payload = payload
        self._json_ok = json_ok

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        if not self._json_ok:
            # 이 포털은 인증 실패 시 json을 요청해도 XML을 준다.
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class _FakeAsyncClient:
    """``provider_fetchers.httpx.AsyncClient`` 대역.

    응답을 호출 순서대로 준다. 경로를 모아 두는 이유는 **페이지 경계**가 맞는지
    세기 위해서다 — 이 포털은 ``limit/offset``이 아니라 ``START_INDEX/END_INDEX``
    라서 한 칸 어긋나면 행이 겹치거나 빠진다.
    """

    responses: list[_FakeResponse] = []
    instances: list[_FakeAsyncClient] = []

    def __init__(self, *, base_url: str, timeout: float) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.paths: list[str] = []
        self.closed = False
        _FakeAsyncClient.instances.append(self)

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.closed = True

    async def get(self, path: str) -> _FakeResponse:
        self.paths.append(path)
        index = len(self.paths) - 1
        return type(self).responses[index]


def _install(
    monkeypatch: pytest.MonkeyPatch, responses: list[_FakeResponse]
) -> type[_FakeAsyncClient]:
    _FakeAsyncClient.responses = responses
    _FakeAsyncClient.instances = []
    monkeypatch.setattr(provider_fetchers.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def _settings(key: str | None = "seoul-key") -> Any:
    secret = None if key is None else SimpleNamespace(get_secret_value=lambda: key)
    return SimpleNamespace(seoul_open_data_api_key=secret)


def _rows(start: int, count: int) -> list[dict[str, Any]]:
    return [{"STORE_SEQ_NO": start + offset} for offset in range(count)]


def _ok(rows: list[dict[str, Any]], total: int) -> _FakeResponse:
    return _FakeResponse(
        {
            _SERVICE: {
                "list_total_count": total,
                "RESULT": {"CODE": "INFO-000", "MESSAGE": "정상 처리되었습니다"},
                "row": rows,
            }
        }
    )


async def test_it_walks_pages_by_index_and_stops_at_the_declared_total() -> None:
    """페이지 경계는 **받은 행 수**로 전진한다.

    선언 총계로 계산해 건너뛰면 원천이 총계를 잘못 주는 날 행이 통째로 빠진다.
    """

    total = _SEOUL_OPEN_DATA_PAGE_SIZE + 5
    with pytest.MonkeyPatch.context() as monkeypatch:
        client = _install(
            monkeypatch,
            [
                _ok(_rows(1, _SEOUL_OPEN_DATA_PAGE_SIZE), total),
                _ok(_rows(_SEOUL_OPEN_DATA_PAGE_SIZE + 1, 5), total),
            ],
        )
        received = [row async for row in fetch_seoul_open_data_bookstores(_settings())]

    assert len(received) == total
    assert client.instances[0].paths == [
        f"/seoul-key/json/{_SERVICE}/1/{_SEOUL_OPEN_DATA_PAGE_SIZE}/",
        f"/seoul-key/json/{_SERVICE}/{_SEOUL_OPEN_DATA_PAGE_SIZE + 1}/"
        f"{_SEOUL_OPEN_DATA_PAGE_SIZE * 2}/",
    ]
    assert client.instances[0].closed is True


async def test_a_past_the_end_request_ends_the_stream_instead_of_raising() -> None:
    """범위를 넘기면 서비스 봉투 없이 ``RESULT``만 온다 — 정상 종료다.

    실측: ``{"RESULT":{"CODE":"INFO-200","MESSAGE":"해당하는 데이터가 없습니다."}}``.
    이것을 오류로 읽으면 마지막 페이지가 딱 맞게 떨어질 때마다 run이 빨개진다.
    """

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(
            monkeypatch,
            [
                _ok(_rows(1, _SEOUL_OPEN_DATA_PAGE_SIZE), _SEOUL_OPEN_DATA_PAGE_SIZE),
                _FakeResponse({"RESULT": {"CODE": "INFO-200"}}),
            ],
        )
        received = [row async for row in fetch_seoul_open_data_bookstores(_settings())]

    # 총계와 받은 수가 같으므로 두 번째 요청 없이 끝나야 하지만, 총계를 못 믿는
    # 날에도 INFO-200이 안전하게 멈춘다.
    assert len(received) == _SEOUL_OPEN_DATA_PAGE_SIZE


async def test_an_error_code_in_a_200_body_is_not_treated_as_empty() -> None:
    """HTTP 200 + 오류 코드를 빈 결과로 삼키면 **거짓 전량 적재**가 된다.

    이 asset은 ``authoritative_snapshot_complete=True``로 적재한다. 조용한 0건은
    그 dataset의 sync cursor를 전진시켜 수집 실패를 신선한 성공으로 보이게 한다.
    """

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, [_FakeResponse({"RESULT": {"CODE": "ERROR-310"}})])
        with pytest.raises(SeoulOpenDataError, match="ERROR-310"):
            [row async for row in fetch_seoul_open_data_bookstores(_settings())]


async def test_an_xml_body_for_a_json_request_is_a_clear_failure() -> None:
    """인증 실패는 ``json``을 요청해도 XML로 온다 — 파싱 실패를 그대로 드러낸다.

    본문을 예외 메시지에 싣지 않는다. 이 포털은 인증키를 **경로**에 받으므로
    본문이나 URL을 로그에 실으면 키가 샌다.
    """

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, [_FakeResponse(None, json_ok=False)])
        with pytest.raises(SeoulOpenDataError) as excinfo:
            [row async for row in fetch_seoul_open_data_bookstores(_settings())]

    assert "seoul-key" not in str(excinfo.value)


async def test_a_never_ending_feed_hits_the_page_ceiling_loudly() -> None:
    """총계를 신뢰할 수 없을 때도 무한히 돌지 않는다.

    조용한 절단 대신 시끄러운 실패다 — 산사태 사고에서 배운 모양 그대로다.
    """

    full = _ok(_rows(1, _SEOUL_OPEN_DATA_PAGE_SIZE), 10**9)
    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, [full] * (_SEOUL_OPEN_DATA_MAX_PAGES + 1))
        with pytest.raises(ProviderPaginationOverrun, match="서울 책방 page 상한"):
            [row async for row in fetch_seoul_open_data_bookstores(_settings())]


async def test_the_missing_key_says_which_portal_it_belongs_to() -> None:
    """data.go.kr 키로는 이 포털이 열리지 않는다 — 오류가 그것을 말해야 한다."""

    with pytest.raises(ProviderCredentialMissing) as excinfo:
        [row async for row in fetch_seoul_open_data_bookstores(_settings(None))]

    message = str(excinfo.value)
    assert "SEOUL_OPEN_DATA_API_KEY" in message
    assert "DATA_GO_KR_SERVICE_KEY" in message


async def test_the_file_data_fetcher_routes_the_seoul_dataset_to_the_new_source() -> None:
    """**분기가 fetcher 안에 있어야 한다.**

    호출자가 둘이다 — Dagster resource와 feature-update worker. 한쪽에만 넣으면
    경로마다 원천이 달라져, 큐로 도는 prod만 죽은 원천을 계속 부른다.
    """

    with pytest.MonkeyPatch.context() as monkeypatch:
        client = _install(monkeypatch, [_ok(_rows(1, 2), 2)])
        received = [
            row
            async for row in fetch_datagokr_file_data_records(
                _settings(), dataset_key="datagokr_seoul_bookstores"
            )
        ]

    assert len(received) == 2
    assert _SERVICE in client.instances[0].paths[0]


def test_the_seoul_page_ceiling_has_headroom_over_the_observed_rows() -> None:
    """상한은 실측의 배수여야 한다 — 실측에 붙여 두면 원천이 조금만 자라도 잘린다."""

    needed_pages = math.ceil(
        _SEOUL_BOOKSTORE_DECLARED_ROWS / _SEOUL_OPEN_DATA_PAGE_SIZE
    )
    assert needed_pages * 2 <= _SEOUL_OPEN_DATA_MAX_PAGES
    # 상한은 여전히 **천장**이어야 한다.
    assert _SEOUL_OPEN_DATA_MAX_PAGES < 1_000
    # 실측 상수를 낮춰 위 검사를 통과시키는 길을 막는다.
    assert _SEOUL_BOOKSTORE_DECLARED_ROWS >= 606
