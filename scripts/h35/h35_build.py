"""T-VN-H35 step 2 — candidate 이미지를 **build만** 한다. 컨테이너를 만들지 않는다.

왜 CLI를 못 쓰나: ``ktdctl pinvi-pair deploy --build``는 ``cli.py:122``가 ``recreate=True``를
하드코딩해 빌드와 활성화를 한 번에 한다. 그런데 API entrypoint가 uvicorn 기동 **전에**
``alembic upgrade head``를 돌리고 0069만 8~18분이라, compose의 ``--wait-timeout 120``(하드코딩)에
걸려 **마이그레이션이 도는 중인 컨테이너를 뜯으며 자동 롤백이 발동한다.**

``_prepare_c6c_candidate_pair``는 빌드·태깅만 하고 실행 컨테이너를 전혀 보지 않는다
(``docker inspect <container>`` 호출 없음). 그래서 이 단계에서 쓴다.

**주의**: 이 빌드는 ``:latest-main`` 5개를 그 자리에서 덮는다. 직전 step에서
``ktm-h35-rollback/*:c8ed6164`` 태그로 현행 pair를 고정해 뒀다.
"""

import os
import sys

os.environ["HOME"] = "/home/digitie"

CACHE_MGR = "/home/digitie/.cache/c7-final.pihf0x9o/manager"
os.chdir(CACHE_MGR)
sys.path.insert(0, os.path.join(CACHE_MGR, "backend", "src"))


def main() -> None:
    from kor_travel_docker_manager.services.c6c_deployment import (
        c6c_deployment_lock,
        load_c6c_deployment_config_from_environment,
    )
    from kor_travel_docker_manager.services.compose_service import (
        compose_service,
        get_c6c_deployment_lock_path,
    )

    print("lock 획득 중 …")
    with c6c_deployment_lock(get_c6c_deployment_lock_path()):
        print("lock OK")
        tx, _ = compose_service._capture_transaction_unlocked(derive_manifest_path=True)
        env = tx.environment.effective
        print(f"  environment mode = {env.get('KTDM_ENVIRONMENT', '(미설정)')}")

        cfg = load_c6c_deployment_config_from_environment(env)
        from kor_travel_docker_manager.services.compose_service import (
            _derive_c6c_build_provenance,
        )

        prov = _derive_c6c_build_provenance(env, compose_path=tx.environment.compose_path)
        print(f"  build provenance = map {getattr(prov, 'map_source_revision', '?')[:12]} / "
              f"pinvi {getattr(prov, 'pinvi_source_revision', '?')[:12]}")

        print("\n=== build 시작 (컨테이너 무변경) ===")
        pair, build_result = compose_service._prepare_c6c_candidate_pair(
            cfg, build=True, build_provenance=prov, transaction=tx
        )
        print("\n=== build 완료 ===")
        for field in (
            "map_source_revision",
            "pinvi_source_revision",
            "map_image_id",
            "map_ui_image_id",
            "map_dagster_image_id",
            "map_dagster_daemon_image_id",
            "pinvi_image_id",
        ):
            print(f"  {field} = {getattr(pair, field, '?')}")
        rc = getattr(build_result, "returncode", None)
        print(f"  build returncode = {rc}")


main()
