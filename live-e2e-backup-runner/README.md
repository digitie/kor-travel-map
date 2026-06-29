# n150 live e2e backup runner

이 디렉터리는 n150 live admin e2e에서 `/admin/backups`의 실제 backup/restore command를
검증하기 위한 tracked runner다.

- 비밀값은 담지 않는다. DB 접속 정보는 API/Dagster 컨테이너의 기존 환경변수를 사용한다.
- n150 docker-manager 배포 topology에 맞춰 host-network PostgreSQL client 컨테이너와
  기존 RustFS 컨테이너 volume을 사용한다.
- 운영 hot-swap apply는 자동 실행하지 않는다. `swap.sh`는 plan/검증용 출력만 제공하고
  `KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY=1`이면 실패한다.

n150 local compose override는 이 디렉터리를 `KOR_TRAVEL_MAP_API_BACKUP_PROJECT_ROOT`로
가리키고, script path는 `backup.sh`, `restore.sh`, `swap.sh`를 사용한다.
