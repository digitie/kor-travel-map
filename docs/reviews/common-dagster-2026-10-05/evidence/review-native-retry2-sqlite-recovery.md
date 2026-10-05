# Native retry2 SQLite 초기화 독립 검증

검토일: 2026-10-06. 범위는 ignored native 하니스의 SQLite 사전 초기화 변경 및 launcher delta이다. 제품·운영 소스 변경이나 운영 성공 판정에 해당하지 않는다.

고정 해시:

- retry2 source: 3bc13c28c833a4179c0e40dc0a0c1fc670e80a8f76d85dc6f1e84a2b28d3d126
- retry2 launcher: bc9ba70631629670d1ed3ada6433ea3f49eff2248d4bf42fceb814214da9e8c0
- 원본 native source: 64813b455c2f0b3c43ef3c37f16d26788eea87d8381da2d670ccce2e911e61d3

좁은 소스 판정 PASS. 원본 대비 daemon Popen 이전에 DagsterInstance.from_config(str(root))의 with/pass로 초기화·dispose를 완료하는 4줄만 추가됨을 직접 byte 비교했다. DAGSTER_HOME과 격리 yaml/작업 파일 작성 후 bootstrap이 수행된다. launcher는 retry 이름·전용 evidence 경로·readonly source 경로·해시만 바뀌었으며, 비root UID/GID·새 디렉터리 검증·network none·메모리/CPU·mount 경계를 유지한다. source와 launcher outer/remote compile은 PASS.

직접 수행: 기존 로컬 테스트 Python /home/digitie/.cache/map-common-recovery-venv/bin/python의 실제 Dagster 1.13.24로 본인 ext4 cache의 새 디렉터리에 같은 telemetry/run_monitoring 설정을 만들었다. from_config 컨텍스트를 종료한 뒤 sqlite_master에서 runs 테이블이 하나의 DB에 생성된 것을 확인했다. 이어서 별도 프로세스 4개가 동시에 from_config를 열어 get_runs_count()==0을 확인하고 정상 종료했다. daemon 및 작업 실행은 하지 않았다.

결과: runs_table_initialized=true, parallel_reopen_pass=4, only_delta_verified=true, bootstrap_before_daemon=true, compile_source_outer_remote=PASS, local_dagster_version=1.13.24, actual_operating_calls=0.

본인 재현 사본: /home/digitie/.cache/recovery-native-retry2-bootstrap-probe.py. 명령은 해당 로컬 테스트 Python으로 이 사본을 실행한다. 모든 SQLite 변경은 본인 새 cache 디렉터리 안에서만 발생했다.

실행·판정 경계: N150 SSH/Docker/DB·이미지 UID 조회·컨테이너 launch·daemon fault 테스트·실제 receipt 수집은 NOT_RUN. 부트스트랩 실패 시 daemon 시작 전에 예외로 종료하며 최종 성공 receipt를 생성하지 않는다. 이후 native timeout 태그의 정확성이나 세 fault의 운영 성공은 이 검증이 증명하지 않는다. 작성자가 보고한 retry1 실패와 retry2 운영 실행은 본인 검증으로 합산하지 않는다. 이전 실패 원문과 제품 FULL 판정은 불변이다.
