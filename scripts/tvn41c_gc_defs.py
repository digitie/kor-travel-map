"""T-VN-41C GC 검증용 Dagster code location.

**실물을 그대로 쓴다** — job도 schedule도 `maintenance.py`가 정의한 객체를 import한다.
정의를 복제하면 cron override 해석(`cron_for_schedule`이 import 시점에 도는 것)과
`default_status=STOPPED`라는 검증 대상 자체가 사본이 되어 의미가 없다.

다만 운영 definitions 전체를 띄우면 `default_status=RUNNING`인 분당 schedule들이
격리 DB에 같이 tick을 쏜다. GC tick 하나를 관측하는 데 필요 없고 호스트에 부담만
되므로 code location은 GC job/schedule로만 좁힌다.
"""

from __future__ import annotations

from dagster import Definitions

from kortravelmap.dagster.maintenance import (
    CACHE_TARGET_SNAPSHOT_GC_SCHEDULES,
    cache_target_snapshot_gc_job,
)
from kortravelmap.dagster.resources import kor_travel_map_client_resource

defs = Definitions(
    jobs=[cache_target_snapshot_gc_job],
    schedules=CACHE_TARGET_SNAPSHOT_GC_SCHEDULES,
    resources={"kor_travel_map_client": kor_travel_map_client_resource},
)
