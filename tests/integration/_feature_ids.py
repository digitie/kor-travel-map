"""테스트 시드용 **결정적** feature 식별자.

## 왜 이 모듈이 있는가

T-VN-39 재키 뒤 `feature.features.feature_id`는 uuid다. 그런데 이 저장소의 통합
테스트는 시드 식별자에 `"admin-map-draft"` · `"feature-admin-lock-a"`처럼 **읽어서
알아볼 수 있는 이름**을 써 왔고, 그 이름이 곧 테스트를 읽는 사람의 지도였다.

두 가지를 다 지키는 방법은 이름을 **키가 아니라 씨앗**으로 쓰는 것이다. 같은
라벨은 언제나 같은 uuid를 내므로 픽스처 사이의 참조가 성립하고, 다른 라벨은 사실상
겹치지 않는다. 손으로 uuid를 적어 넣는 대안은 (1) 읽으면 무엇인지 알 수 없고
(2) 파일이 늘수록 충돌 위험이 쌓인다.

## 쓰면 안 되는 곳

**정렬 순서를 의미로 쓰는 테스트.** 유도값의 순서는 라벨의 사전순과 무관하다.
`ck_dedup_pair_order`처럼 `a < b`를 요구하는 자리는 순서를 눈으로 확인할 수 있는
리터럴을 그 파일이 직접 들어야 한다.

**legacy `f_*`가 입력인 자리.** provider DTO의 식별자로 `load_bundle`에 들어가는
값, alias 해석의 입력, "없는 참조"를 증명하는 값은 그대로 `f_*`가 맞다
(ADR-098 결정 6).
"""

from __future__ import annotations

import hashlib
import uuid

__all__ = ["feature_uuid"]


def feature_uuid(label: str) -> str:
    """``label``에서 결정적으로 유도한 canonical uuid 문자열.

    UUIDv7 **모양**을 만든다(버전·변형 비트만 맞춘다). 앞 48비트가 시각이라는
    UUIDv7의 의미는 없다 — 여기서 필요한 것은 "uuid 컬럼이 받아 주는 값"과
    "라벨당 하나"뿐이고, 시각 의미를 흉내 내면 시각으로 정렬된다고 오해할 여지가
    생긴다.

    >>> feature_uuid("admin-map-draft") == feature_uuid("admin-map-draft")
    True
    >>> feature_uuid("a") != feature_uuid("b")
    True
    """
    raw = bytearray(hashlib.sha256(label.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # RFC 4122 variant
    return str(uuid.UUID(bytes=bytes(raw)))
