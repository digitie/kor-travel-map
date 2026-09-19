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
    """``httpx.Response`` 대역.

    ``status_code``를 받는 이유는 **키 유출 경로를 실제로 지나가기 위해서다.**
    종전 대역은 상태를 몰라 오류 응답을 흉내낼 수 없었고, 그래서 '키를 예외에
    싣지 않는다'는 단언이 **유출될 수 없는 가지에만 걸려 있었다**(적대 리뷰 지적).
    """

    def __init__(
        self, payload: Any, *, json_ok: bool = True, status_code: int = 200
    ) -> None:
        self._payload = payload
        self._json_ok = json_ok
        self.status_code = status_code

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

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

    **총계를 일부러 크게 준다.** 종전 검사는 첫 페이지에서 ``start > total``로
    이미 끝나 두 번째 응답을 **소비하지 않았다** — 그 분기를 ``raise``로 바꿔도
    초록이었다(적대 리뷰 지적). 요청이 실제로 두 번 나갔는지도 함께 센다.
    """

    with pytest.MonkeyPatch.context() as monkeypatch:
        client = _install(
            monkeypatch,
            [
                _ok(_rows(1, _SEOUL_OPEN_DATA_PAGE_SIZE), 10**6),
                _FakeResponse({"RESULT": {"CODE": "INFO-200"}}),
            ],
        )
        received = [row async for row in fetch_seoul_open_data_bookstores(_settings())]

    assert len(received) == _SEOUL_OPEN_DATA_PAGE_SIZE
    assert len(client.instances[0].paths) == 2


async def test_a_first_page_with_no_rows_is_a_failure_not_an_empty_snapshot() -> None:
    """**첫 페이지 0건은 종료가 아니라 실패다.**

    이 fetcher가 흘리는 행은 ``authoritative_snapshot_complete=True``로 봉인된다.
    조용한 0건은 그 dataset의 sync cursor를 전진시켜 **수집 실패를 신선한 성공으로
    위장한다** — 이 PR이 MCST에서 막겠다고 한 바로 그 모양이다.
    """

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, [_ok([], 0)])
        with pytest.raises(SeoulOpenDataError, match="첫 페이지가 0건"):
            [row async for row in fetch_seoul_open_data_bookstores(_settings())]


async def test_a_first_request_saying_no_data_is_also_a_failure() -> None:
    """첫 요청이 ``INFO-200``이면 전량이 사라졌거나 서비스명이 바뀐 것이다."""

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, [_FakeResponse({"RESULT": {"CODE": "INFO-200"}})])
        with pytest.raises(SeoulOpenDataError, match="첫 요청이 INFO-200"):
            [row async for row in fetch_seoul_open_data_bookstores(_settings())]


async def test_a_single_row_object_is_not_read_as_zero_rows() -> None:
    """행이 하나일 때 이 포털은 list가 아니라 object 하나를 준다.

    list가 아니라고 버리면 **1건짜리 응답이 0건으로 보인다** — 위의 첫 페이지
    가드와 합쳐지면 실패로 끝나므로 조용하지는 않지만, 애초에 틀린 판정이다.
    """

    single = _FakeResponse(
        {
            _SERVICE: {
                "list_total_count": 1,
                "RESULT": {"CODE": "INFO-000"},
                "row": {"STORE_SEQ_NO": 7},
            }
        }
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, [single])
        received = [row async for row in fetch_seoul_open_data_bookstores(_settings())]

    assert received == [{"STORE_SEQ_NO": 7}]


async def test_an_http_error_never_carries_the_key_that_sits_in_the_path() -> None:
    """HTTP 오류 메시지에 **인증키가 들어가면 안 된다.**

    이 포털은 인증키를 경로에 받으므로 ``raise_for_status()``가 만드는
    ``httpx.HTTPStatusError``는 키가 실린 URL 전체를 담는다. 그 메시지는 Dagster
    step-failure 이벤트와 compute log에 영속 기록되고, 큐 경로는
    ``raise ... from exc``로 체인까지 보존한다(적대 리뷰 지적). 형제 라이브러리
    ``python-datagokr-api``가 같은 이유로 키를 지우고 체인을 끊는다.
    """

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, [_FakeResponse(None, status_code=502)])
        with pytest.raises(SeoulOpenDataError) as excinfo:
            [row async for row in fetch_seoul_open_data_bookstores(_settings())]

    message = str(excinfo.value)
    assert "502" in message
    assert "seoul-key" not in message
    assert "openapi.seoul.go.kr" not in message
    # 체인도 끊는다 — `__cause__`에 원본 예외가 남으면 traceback으로 다시 샌다.
    assert excinfo.value.__cause__ is None


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
    assert excinfo.value.__cause__ is None


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
