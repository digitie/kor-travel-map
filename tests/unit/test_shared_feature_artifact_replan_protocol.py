"""정상 stale만 재계획으로 분류하고 일반 오류/constraint 실패를 삼키지 않는다."""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.integration.test_shared_feature_artifact_replan import (
    _artifact,
    _bundle,
    _selected_stale,
)


@pytest.mark.parametrize(
    ("state", "cause_state", "constraint", "message", "expected"),
    [
        ("40001", "40001", None, "manifest source changed; replan", True),
        ("23514", "23514", None, "manifest source changed; replan", False),
        ("55P03", "55P03", None, "manifest source changed; replan", False),
        ("40001", "23514", None, "manifest source changed; replan", False),
        ("40001", "40001", "ck_executor_fence", "manifest source changed; replan", False),
        ("40001", "40001", None, "unknown attempt or owner", False),
        ("40001", "40001", None, "could not serialize access", False),
        ("08006", "08006", None, "manifest source changed; replan", False),
    ],
)
def test_only_selected_unconstrained_kernel_stale_is_accepted(
    state, cause_state, constraint, message, expected
):
    cause = SimpleNamespace(sqlstate=cause_state, constraint_name=constraint, message=message)
    error = SimpleNamespace(orig=SimpleNamespace(sqlstate=state, __cause__=cause))
    assert _selected_stale(error) is expected


def test_unstructured_driver_failure_is_not_replan():
    assert not _selected_stale(SimpleNamespace(orig=SimpleNamespace(sqlstate="40001")))


def test_artifact_bytes_are_identical_across_independent_python_hash_seeds():
    # frozenset presence를 model_dump_json으로 직렬화하던 초안의 process별 순서 회귀.
    code = """import hashlib,sys
from tests.integration.test_shared_feature_artifact_replan import _artifact,_decode_artifact
bundle=_decode_artifact(sys.stdin.buffer.read())
print(hashlib.sha256(_artifact(bundle)).hexdigest())
"""
    artifact = _artifact(_bundle("fixed-source", "fixed-name")).decode()
    digests = []
    for seed in ["1", "2"]:
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            env={**os.environ, "PYTHONHASHSEED": seed},
            input=artifact,
            capture_output=True,
            text=True,
            check=True,
            timeout=12,
        )
        digest = result.stdout.strip()
        assert len(digest) == 64
        digests.append(digest)
    assert digests[0] == digests[1]
