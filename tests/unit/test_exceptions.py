"""``test_exceptions`` — ``krtour.map.core.exceptions`` 계층 검증.

``docs/backend-package.md §5`` + ``docs/debug-ui-package.md §6.4`` 명세 준수.
"""

from __future__ import annotations

import pytest

from krtour.map.core.exceptions import (
    DuplicateFeatureError,
    FeatureNotFoundError,
    FileStoreError,
    ImportJobConflictError,
    KrtourMapError,
    ProviderError,
    SourceRecordNotFoundError,
    ValidationError,
)


def test_base_exception_is_subclass_of_exception() -> None:
    """``KrtourMapError``는 builtin ``Exception``을 상속한다."""
    assert issubclass(KrtourMapError, Exception)


@pytest.mark.parametrize(
    "exc_cls",
    [
        ValidationError,
        FeatureNotFoundError,
        SourceRecordNotFoundError,
        DuplicateFeatureError,
        ImportJobConflictError,
        ProviderError,
        FileStoreError,
    ],
)
def test_all_subclasses_inherit_from_base(exc_cls: type[KrtourMapError]) -> None:
    """모든 도메인 예외는 ``KrtourMapError``를 상속해야 한다.

    호출자가 ``except KrtourMapError:`` 한 줄로 라이브러리 발 예외를 모두
    catch할 수 있어야 한다 (``docs/backend-package.md §5``).
    """
    assert issubclass(exc_cls, KrtourMapError)


def test_raise_and_catch_via_base() -> None:
    """``KrtourMapError``로 모든 서브클래스를 catch할 수 있다."""
    with pytest.raises(KrtourMapError) as exc_info:
        raise FeatureNotFoundError("feature_id=f_abc not found")
    assert "feature_id=f_abc not found" in str(exc_info.value)


def test_raise_and_catch_specific() -> None:
    """특정 서브클래스로도 catch할 수 있다."""
    with pytest.raises(DuplicateFeatureError):
        raise DuplicateFeatureError("conflict")


def test_exception_message_preserved() -> None:
    """예외 메시지가 ``str(exc)``로 그대로 전달된다."""
    msg = "raw payload hash mismatch on f_1100000000_p_abc"
    exc = ValidationError(msg)
    assert str(exc) == msg


def test_all_exported_via_module() -> None:
    """``__all__``에 명시된 심볼이 모두 module에서 import 가능하다."""
    from krtour.map.core import exceptions as exc_mod

    expected = {
        "KrtourMapError",
        "ValidationError",
        "FeatureNotFoundError",
        "SourceRecordNotFoundError",
        "DuplicateFeatureError",
        "ImportJobConflictError",
        "ProviderError",
        "FileStoreError",
    }
    assert set(exc_mod.__all__) == expected
    for name in expected:
        assert hasattr(exc_mod, name), f"{name} not in exceptions module"


def test_exceptions_reexported_from_core_package() -> None:
    """``krtour.map.core``에서 직접 import 가능해야 한다 (편의 re-export)."""
    from krtour.map import core

    for name in (
        "KrtourMapError",
        "ValidationError",
        "FeatureNotFoundError",
        "SourceRecordNotFoundError",
        "DuplicateFeatureError",
        "ImportJobConflictError",
        "ProviderError",
        "FileStoreError",
    ):
        assert hasattr(core, name), f"{name} not re-exported from krtour.map.core"
