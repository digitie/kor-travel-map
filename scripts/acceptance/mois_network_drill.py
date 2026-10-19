"""MOIS loader의 실제 연결 단절·native retry·복구: 소유 namespace 전용."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def namespace(kind):
    return os.readlink(f"/proc/self/ns/{kind}")


def guard(parent_net, parent_user):
    if namespace("net") == parent_net or namespace("user") == parent_user or os.getuid() != 0:
        raise RuntimeError("isolated namespace required")
    mapping = Path("/proc/self/uid_map").read_text().split()
    if len(mapping) != 3 or mapping[0] != "0" or mapping[1] == "0" or mapping[2] != "1":
        raise RuntimeError("non-root owner mapping required")


def inner(parent_net, parent_user, smoke):
    guard(parent_net, parent_user)
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    import httpx
    from dagster import DagsterInstance, job, op
    from kortravelmap.dagster.assets import MOIS_LOAD_RETRY_POLICY
    from kortravelmap.dagster.mois_chunked_load import MOIS_LOAD_CHUNK_SIZE, resolve_mois_load_plan
    from pydantic import SecretStr

    from kortravelmap.geocoding import (
        KorTravelGeoRestClient,
        geo_http_timeout,
        kor_travel_geo_reverse_geocoder,
    )
    from kortravelmap.settings import KorTravelMapSettings

    fixture_path = ROOT / "packages/kor-travel-map-dagster/tests/test_mois_chunked_load.py"
    spec = importlib.util.spec_from_file_location("mois_fixture", fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixture
    spec.loader.exec_module(fixture)
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append(self.path)
            assert self.path == "/v2/reverse"
            body = json.dumps(
                {
                    "status": "OK",
                    "candidates": [
                        {
                            "confidence": 1.0,
                            "match_kind": "parcel",
                            "address": {"full": "합성 검증 주소", "legal_dong_code": "1111010100"},
                            "region": {"sig_cd": "11110", "bjd_cd": "1111010100"},
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    installed = False

    def close_server():
        try:
            server.shutdown()
        finally:
            server.server_close()
            thread.join(timeout=5)
            assert not thread.is_alive()

    try:
        port = server.server_address[1]
        rule = [
            "OUTPUT",
            "-o",
            "lo",
            "-p",
            "tcp",
            "--dport",
            str(port),
            "--syn",
            "-j",
            "DROP",
        ]
        settings = KorTravelMapSettings()
        plan = resolve_mois_load_plan(settings, service_slugs=("bakeries",))
        assert plan.run_budget_seconds == 14400
        assert plan.geocode_concurrency == 2
        assert geo_http_timeout(settings).connect == 4
        assert MOIS_LOAD_CHUNK_SIZE == 500
        assert MOIS_LOAD_RETRY_POLICY.max_retries == 1
        assert MOIS_LOAD_RETRY_POLICY.delay == 300
        records = [
            fixture._Record(
                service_slug="bakeries",
                mng_no=f"fixture-{i:04d}",
                lon=126.9 + i / 10000,
                lat=37.5,
            )
            for i in range(500)
        ]

        async def load(db, context=None):
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=geo_http_timeout(settings)
            ) as http:
                client = KorTravelGeoRestClient(http, api_key=SecretStr("synthetic-fixture-only"))
                geo = kor_travel_geo_reverse_geocoder(client, region_fallback_radius_km=0.1)
                return await fixture._run(
                    records, db, geocoder=geo, plan=plan, context=context, strict_address="drop"
                )
    except BaseException:
        close_server()
        raise

    try:
        baseline_db = fixture._FakeDb()
        asyncio.run(load(baseline_db))
        assert len(baseline_db.current) == 500
        before_calls = len(calls)
        db = fixture._FakeDb()
        subprocess.run(["iptables", "-A", *rule], check=True)
        installed = True
        start = time.monotonic()
        if smoke:
            from kortravelmap.core.exceptions import GeoRequestError

            try:
                asyncio.run(load(db))
            except GeoRequestError:
                native_status = "NOT_RUN_SMOKE"
            else:
                raise AssertionError("expected typed failure")
            retries = 0
        else:

            @op(retry_policy=MOIS_LOAD_RETRY_POLICY)
            def fixture_mois_load(context):
                asyncio.run(load(db, context))

            @job
            def fixture_mois_job():
                fixture_mois_load()

            with (
                tempfile.TemporaryDirectory(prefix="map-mois-native-") as tmp,
                DagsterInstance.ephemeral(
                    tempdir=tmp, settings={"telemetry": {"enabled": False}}
                ) as instance,
            ):
                result = fixture_mois_job.execute_in_process(
                    instance=instance, raise_on_error=False
                )
                native_status = instance.get_run_by_id(result.run_id).status.value
                retries = sum(e.event_type_value == "STEP_UP_FOR_RETRY" for e in result.all_events)
                assert not result.success
                assert native_status == "FAILURE"
                assert retries == 1
        elapsed = time.monotonic() - start
        assert elapsed < plan.run_budget_seconds * 0.1
        assert db.current == {}
        assert db.commits == []
        assert db.seals == 0
        assert len(calls) == before_calls
        counters = subprocess.check_output(
            ["iptables", "-L", "OUTPUT", "-n", "-v", "-x"], text=True
        )
        drop = [line.split() for line in counters.splitlines() if "DROP" in line]
        assert len(drop) == 1
        assert int(drop[0][0]) > 0
        subprocess.run(["iptables", "-D", *rule], check=True)
        installed = False
        asyncio.run(load(db))
        assert db.current == baseline_db.current
        assert len(db.current) == 500
        recovered_commits = len(db.commits)
        calls_after_recovery = len(calls)
        asyncio.run(load(db))
        assert db.current == baseline_db.current
        assert len(calls) == calls_after_recovery
        return {
            "status": "PASS",
            "native_status": native_status,
            "native_retries": retries,
            "elapsed_failure_seconds": elapsed,
            "run_budget_seconds": 14400,
            "failure_limit_seconds": 1440,
            "records": 500,
            "chunk_size": 500,
            "concurrency": 2,
            "connect_timeout_seconds": 4,
            "drop_packets": int(drop[0][0]),
            "failed_chunk_commits": 0,
            "recovered_commits": recovered_commits,
            "recovered_unique_entities": len(db.current),
            "replay_http_calls": 0,
            "geocoding_sha256": hashlib.sha256(
                (ROOT / "src/kortravelmap/geocoding.py").read_bytes()
            ).hexdigest(),
            "scope": (
                "real HTTP/native retry/MOIS loader; synthetic records and "
                "transaction-semantics DB fixture; no provider fetch"
            ),
        }
    finally:
        try:
            if installed:
                subprocess.run(["iptables", "-D", *rule], check=True)
        finally:
            close_server()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inner", nargs=2)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.inner:
        print(json.dumps(inner(*args.inner, args.smoke)))
        return
    if os.getuid() == 0:
        raise RuntimeError("launch as an unprivileged user")
    original = (namespace("net"), namespace("user"))
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    env["PYTHONPATH"] = (
        str(ROOT / "src")
        + ":"
        + str(ROOT / "packages/kor-travel-map-dagster/src")
        + ":"
        + env.get("PYTHONPATH", "")
    )
    command = [
        "unshare",
        "-Urn",
        sys.executable,
        str(Path(__file__).resolve()),
        "--inner",
        *original,
    ]
    if args.smoke:
        command.append("--smoke")
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=600, check=False
    )
    assert original == (namespace("net"), namespace("user"))
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
