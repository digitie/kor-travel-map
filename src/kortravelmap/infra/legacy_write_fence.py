"""legacy ``curated_*`` write fence (T-VN-40A).

T-VN-40의 설계(`docs/reports/t-vn-40-curation-write-model-plan-2026-08-11.md` §40A step 2)는
"`curated_features`를 직접 쓰는 repository/trigger/Dagster/merge/admin command를 inventory하고
**new legacy write를 DB/ACL/static gate로 막는다**"고 했다. 구현 PR #974는 이 단계를 빼고
병합됐고, 2026-08-18 재조사에서 legacy와 canonical이 **양쪽 다 쓰기 가능**한 채였다는 것이
드러났다.

이 모듈은 그 fence의 **static 층**이다. 세 층이 겹친다:

- **ACL 층** — `runtime_privileges._FEATURE_TABLE_PRIVILEGES`에서 legacy 표의 write 권한을
  뺐다. `reconcile_runtime_privileges`가 `REVOKE ALL` 뒤 그 표대로만 GRANT하므로 표에 없는
  권한은 DB에 존재하지 않는다. 우회 코드가 있어도 DB가 거부한다.
- **static 층 (여기)** — legacy repository의 write 함수가 첫 줄에서
  :func:`assert_legacy_write_allowed`를 부른다. ACL 층보다 먼저, 더 읽기 좋은 오류로 죽는다.
- **route 층** — legacy admin write route가 ``410 Gone``을 돌려준다. 설계는 "redirect/no-op
  parameter를 두지 않는다"고 했다(plan §40B step 4).

**왜 세 층이 필요한가.** 하나만 두면 그 하나가 조용히 풀렸을 때 아무도 모른다. ACL은
migration 실수로 다시 열릴 수 있고, static은 새 호출자가 우회할 수 있고, route는 다른
router가 같은 repo를 부를 수 있다. 셋이 서로를 감시한다.

**이 fence는 영구가 아니다.** T-VN-40C가 legacy 표 자체를 물리 삭제하면 이 모듈도 함께
사라진다 — 그때까지의 다리다.

읽기는 막지 않는다. soak·reconciliation 동안 legacy를 **읽어서** canonical과 대조해야
하기 때문이다(ADR-075 결정 4).
"""

from __future__ import annotations

from typing import Final

from kortravelmap.core.exceptions import KorTravelMapError

#: fence가 막는 legacy 관계. 이 집합이 `runtime_privileges`의 write 권한 제거와
#: `tests/lint/test_legacy_write_fence.py`의 검사 대상이다 — 셋이 같은 이름을 봐야 한다.
LEGACY_CURATED_RELATIONS: Final[frozenset[str]] = frozenset({"curated_features"})
# ⚠️ `curated_themes`·`curated_sources`·`curated_source_rules`는 **넣지 않는다.**
# 이름이 `curated_`로 시작해 legacy처럼 보이지만, T-VN-40 계획서(plan:28)가 그 셋을
# "catalog input만 유지"로 정했고 `0207_tvn40_theme_catalog.py`가 T-VN-40에서 새로 만든
# procedure로 그 표에 쓴다. 살아 있는 catalog다. 첫 적용에서 넷을 다 막았다가 이 사실을
# 확인하고 되돌렸다 — 막으면 T-VN-40 자체가 깨진다.
# `curated_feature_detail_snapshots`·`curated_tripmate_copy_snapshots`는 legacy **read**
# 경로의 캐시라 read가 살아 있는 동안 갱신돼야 한다. 40C에서 read와 함께 지운다.


class LegacyWriteFenceError(KorTravelMapError):
    """legacy ``curated_*`` 관계에 대한 쓰기 시도.

    T-VN-40A 이후 legacy 관계는 읽기 전용이다. 정본은 `feature.curation_collections` /
    `feature.curation_items`이고 쓰기 경로는 canonical import(`POST /v1/admin/curations/
    imports/preview` → `.../import-plans/{id}/commit`)와 admin item command다.
    """


def assert_legacy_write_allowed(relation: str, *, operation: str) -> None:
    """legacy 관계 쓰기를 **항상** 거부한다.

    함수 이름이 "allowed"인 것은 호출부에서 의도가 읽히게 하려는 것이다 — 이 함수는
    T-VN-40A 이후로 예외를 던지는 것 외에 아무것도 하지 않는다. "허용 조건"이 생기면
    fence가 아니라 다른 것이 된다.

    Args:
        relation: ``curated_features`` 같은 관계 이름(schema 없이).
        operation: 로그·오류에 실을 동작 이름(``create``·``update`` 등).
    """
    if relation in LEGACY_CURATED_RELATIONS:
        raise LegacyWriteFenceError(
            f"legacy write fenced (T-VN-40A): {operation} on feature.{relation}. "
            "legacy curated_* 관계는 읽기 전용이다. 정본은 curation_collections/"
            "curation_items이고 쓰기 경로는 canonical import·admin item command다."
        )
    # 목록 밖 관계는 이 fence의 관심사가 아니다. 조용히 통과시키지 않고 명시적으로
    # 거부하는 것이 나은지 고민했지만, 그러면 이 함수를 부르는 곳이 fence 대상 판단까지
    # 떠안게 된다. 대상은 위 집합 하나로 고정한다.


__all__ = [
    "LEGACY_CURATED_RELATIONS",
    "LegacyWriteFenceError",
    "assert_legacy_write_allowed",
]
