"""선택 설치된 실제 MCST SDK와 Map 기본 factory의 승인형 CSV 경계."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import httpx
import pytest
from kortravelmap.providers.mcst import McstSlugAttempt, McstSlugFailure
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster.provider_fetchers import fetch_mcst_culture_records


@pytest.mark.parametrize(
    "scenario", ["approved", "captcha", "network", "metadata", "ambiguous", "invalid_content"]
)
async def test_default_factory_uses_native_approval_transport(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    pytest.importorskip("mcst")
    from mcst import _http

    captcha = scenario == "captcha"
    requests: list[tuple[str, str]] = []
    sessions: list[httpx.AsyncClient] = []
    csv = (
        "지역,이름,사업자,소재지,면적(제곱미터),홀,구분\n"
        "서울,검증골프장,사업자,서울특별시,123,18,일반\n"
    )
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("포장/표준산출물/데이터사전.csv", "컬럼명,정의\n이름,명칭\n")
        archive.writestr("포장/본자료.csv", csv.encode("utf-8-sig"))
        if scenario == "ambiguous":
            archive.writestr("포장/다른본자료.csv", csv.encode("utf-8-sig"))

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/data/15118920/fileData.do":
            return httpx.Response(
                200,
                text="""<button onclick="fileDetailObj.fn_fileDataDown(
                    '15118920', 'uddi:fixture', '', '1', '8')">다운로드</button>""",
                headers={"set-cookie": "fixture=ready; Path=/"},
            )
        assert request.headers["cookie"] == "fixture=ready"
        if request.url.path == "/tcs/dss/selectFileDataDownload.do":
            if scenario == "network":
                raise httpx.ReadError("upstream ?token=SECRET_BODY", request=request)
            if scenario == "metadata":
                return httpx.Response(200, json={"status": False, "body": "SECRET_BODY"})
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "atchFileId": "FIXTURE",
                    "fileDetailSn": "1",
                    "dataSetFileDetailInfo": {"publicDataTyDetailCode": "DATY03", "dataNm": "현황"},
                },
            )
        if request.url.path == "/cmm/cmm/check-limit.json":
            return httpx.Response(200, json={"needCaptcha": captcha})
        assert request.url.path == "/cmm/cmm/fileDownload.do"
        assert not captcha
        return httpx.Response(
            200,
            content=b"<html>SECRET_BODY</html>"
            if scenario == "invalid_content"
            else target.getvalue(),
        )

    class NativeFixtureClient(httpx.AsyncClient):
        def __init__(self, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(handle)
            super().__init__(**kwargs)
            sessions.append(self)

    monkeypatch.setattr(_http.httpx, "AsyncClient", NativeFixtureClient)
    records = [
        row
        async for row in fetch_mcst_culture_records(
            KorTravelMapSettings(),
            slugs=("golf_courses_status",),
        )
    ]
    assert records[0] == McstSlugAttempt("golf_courses_status")
    if scenario != "approved":
        reason, retryable, count = {
            "captcha": ("CAPTCHA_REQUIRED", False, 3),
            "network": ("McstNetworkError", True, 2),
            "metadata": ("FILE_METADATA_INVALID", False, 2),
            "ambiguous": ("AMBIGUOUS_CSV", False, 4),
            "invalid_content": ("CSV_INVALID_CONTENT", False, 4),
        }[scenario]
        assert records[1] == McstSlugFailure("golf_courses_status", reason, retryable)
        assert len(requests) == count
        assert "SECRET_BODY" not in str(records)
    else:
        assert records[1] == (
            "golf_courses_status",
            {
                "지역": "서울",
                "이름": "검증골프장",
                "사업자": "사업자",
                "소재지": "서울특별시",
                "면적(제곱미터)": "123",
                "홀": "18",
                "구분": "일반",
            },
        )
        assert [method for method, _path in requests] == ["GET", "POST", "POST", "GET"]
    assert len(sessions) == 1
    assert sessions[0].is_closed
