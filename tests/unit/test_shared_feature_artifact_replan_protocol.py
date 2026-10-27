"""정상 stale만 재계획으로 분류하고 일반 오류/constraint 실패를 삼키지 않는다."""

from types import SimpleNamespace

import pytest

from tests.integration.test_shared_feature_artifact_replan import _selected_stale


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
