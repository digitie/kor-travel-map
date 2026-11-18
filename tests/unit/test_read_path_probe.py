"""읽기 경로 HTTP probe(T-READ-01) — DB 없음, token 비노출, 보고서 모양."""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

import scripts.read_path_probe as probe

pytestmark = pytest.mark.unit

_SECRET = "probe-secret-token-0123456789abcdef"
_PROBE_SOURCE = Path(probe.__file__).read_text(encoding="utf-8")


def _fake_fetch(seen: list[tuple[str, dict[str, str]]]) -> probe.Fetch:
    def fetch(url: str, headers: Mapping[str, str], _timeout: float) -> probe.ProbeResponse:
        seen.append((url, dict(headers)))
        if "/v1/features/in-bounds" in url and "zoom=14" in url:
            data: object = {"items": [{"feature_id": "0f0f0f0f-0000-0000-0000-000000000001"}]}
        else:
            data = {"items": []}
        body = json.dumps({"data": data, "meta": {"duration_ms": 12, "request_id": "r"}})
        return probe.ProbeResponse(status=200, body=body.encode())

    return fetch


def test_probe_imports_no_database_or_application_package() -> None:
    tree = ast.parse(_PROBE_SOURCE)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"kortravelmap", "sqlalchemy", "asyncpg", "psycopg", "httpx"})


def test_service_token_header_matches_api_contract() -> None:
    from kortravelmap.api.auth import SERVICE_TOKEN_HEADER

    assert probe.SERVICE_TOKEN_HEADER == SERVICE_TOKEN_HEADER


def test_token_is_sent_as_header_but_never_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(probe, "_urllib_fetch", _fake_fetch(seen))
    monkeypatch.setattr(probe, "read_psi_io_some_avg60", lambda: 3.5)
    # run_probe의 기본 인자는 정의 때 묶이므로 main이 쓰는 run_probe를 감싼다.
    real_run = probe.run_probe

    def run(**kwargs: object) -> dict[str, object]:
        return real_run(
            fetch=probe._urllib_fetch, psi=probe.read_psi_io_some_avg60, **kwargs
        )

    monkeypatch.setattr(probe, "run_probe", run)
    token_file = tmp_path / "token"
    token_file.write_text(_SECRET + "\n", encoding="utf-8")
    output = tmp_path / "probe.safe.json"

    assert probe.main(
        ["--token-file", str(token_file), "--iterations", "2", "--output", str(output)],
        environ={},
    ) == 0

    stdout = capsys.readouterr().out
    written = output.read_text(encoding="utf-8")
    assert _SECRET not in stdout
    assert _SECRET not in written
    assert all(headers[probe.SERVICE_TOKEN_HEADER] == _SECRET for _url, headers in seen)
    report = json.loads(written)
    names = [case["name"] for case in report["cases"]]
    assert names == [case.name for case in probe.PROBE_CASES] + [probe.DETAIL_CASE_NAME]
    for case in report["cases"]:
        assert case["iterations"] == 2
        assert case["statuses"] == {"200": 2}
        assert case["server_p50_ms"] == 12.0
        assert case["psi_io_some_avg60_before"] == 3.5
    detail = report["cases"][-1]
    assert detail["path"] == "/v1/features/{feature_id}"
    assert "0f0f0f0f" not in written


def test_token_from_env_and_absent_token() -> None:
    assert probe.read_service_token(None, {probe.TOKEN_ENV: f"  {_SECRET} "}) == _SECRET
    assert probe.read_service_token(None, {}) is None


def test_report_schema_is_stable_across_runs() -> None:
    def run() -> dict[str, object]:
        return probe.run_probe(
            base_url="http://127.0.0.1:12701",
            token=None,
            iterations=1,
            fetch=_fake_fetch([]),
            psi=lambda: None,
        )

    first, second = run(), run()
    assert first.keys() == second.keys()
    assert [sorted(case) for case in first["cases"]] == [
        sorted(case) for case in second["cases"]
    ]


def test_non_loopback_target_is_not_written() -> None:
    report = probe.run_probe(
        base_url="http://10.1.2.3:12701",
        token=None,
        iterations=1,
        fetch=_fake_fetch([]),
        psi=lambda: None,
    )
    assert report["target"] == "<non-loopback>"


def test_psi_parser_reads_some_avg60(tmp_path: Path) -> None:
    psi = tmp_path / "io"
    psi.write_text(
        "some avg10=1.00 avg60=7.25 avg300=3.00 total=1\n"
        "full avg10=0.50 avg60=4.00 avg300=1.00 total=1\n",
        encoding="ascii",
    )
    assert probe.read_psi_io_some_avg60(psi) == 7.25
    assert probe.read_psi_io_some_avg60(tmp_path / "missing") is None


def test_transport_errors_are_counted_by_type_only() -> None:
    def failing(_url: str, _headers: Mapping[str, str], _timeout: float) -> probe.ProbeResponse:
        raise TimeoutError("timed out talking to http://10.1.2.3/secret")

    report = probe.run_probe(
        base_url="http://127.0.0.1:12701",
        token=_SECRET,
        iterations=2,
        fetch=failing,
        psi=lambda: None,
        cases=probe.PROBE_CASES[:1],
    )
    case = report["cases"][0]
    assert case["errors"] == {"TimeoutError": 2}
    assert case["wall_p50_ms"] is None
    assert "secret" not in json.dumps(report)


def test_non_200_is_excluded_from_percentiles_and_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unauthorized(url: str, headers: Mapping[str, str], _timeout: float) -> probe.ProbeResponse:
        return probe.ProbeResponse(status=401, body=b"{}")

    monkeypatch.setattr(probe, "read_psi_io_some_avg60", lambda: None)
    real_run = probe.run_probe

    def run(**kwargs: object) -> dict[str, object]:
        return real_run(fetch=unauthorized, psi=probe.read_psi_io_some_avg60, **kwargs)

    monkeypatch.setattr(probe, "run_probe", run)
    token_file = tmp_path / "token"
    token_file.write_text(_SECRET + "\n", encoding="utf-8")
    output = tmp_path / "probe.safe.json"

    assert probe.main(
        ["--token-file", str(token_file), "--iterations", "2", "--output", str(output)],
        environ={},
    ) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert all(case["wall_p50_ms"] is None for case in report["cases"])
