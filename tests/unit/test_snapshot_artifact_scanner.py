"""문자열 내부 구문과 ASCII escape가 기존 snapshot 한도를 바꾸지 않는다."""

import json

import pytest

from kortravelmap.infra import _snapshot_artifact_codec as codec


@pytest.mark.parametrize("profile", list(codec.CodecProfile))
@pytest.mark.parametrize("char", ["a", '"', "\\", "\0", "\b", "\f", "\n", "\r", "\t", "\x1f"])
def test_ascii_encoded_cost_preserves_exact_preflight_boundary(monkeypatch, profile, char):
    # 작은 동일 예산으로 escape 비용 경계를 검증한다. 실제 profile 상수는 바꾸지 않는다.
    monkeypatch.setattr(codec, "_limits", lambda _: (128, 128, 128))
    unit = len(json.dumps(char, ensure_ascii=False)) - 2
    value = char * (118 // unit) + "a" * (118 % unit)
    assert len(json.dumps(value, ensure_ascii=False)) == 120
    codec.preflight((value,), profile=profile)
    with pytest.raises(ValueError, match="unsupported bounded typed snapshot"):
        codec.preflight((value + "a",), profile=profile)


@pytest.mark.parametrize("profile", list(codec.CodecProfile))
def test_quoted_syntax_does_not_hide_outer_depth_overflow(profile):
    quoted = json.dumps('[]{}"\\\n\x00' * 64, ensure_ascii=False)
    wire = ("[" * 64 + quoted + "]" * 64).encode()
    assert codec.guard_wire(wire, profile=profile) == wire.decode()
    with pytest.raises(ValueError, match="unsupported bounded typed snapshot"):
        codec.guard_wire(b"[" + wire + b"]", profile=profile)


@pytest.mark.parametrize("profile", list(codec.CodecProfile))
@pytest.mark.parametrize("wire", [b'"unterminated', b'"trailing\\', b'"\\\n"'])
def test_malformed_quoted_input_still_reaches_json_syntax_rejection(profile, wire):
    value = codec.guard_wire(wire, profile=profile)
    with pytest.raises(json.JSONDecodeError):
        json.loads(value)
