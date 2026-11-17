# tasks-acceptance 아카이브 — `T-VN-M02-TRUNCATE-FENCE` (완료)

> `T-VN-M02-TRUNCATE-FENCE`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-11-17).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 0개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-VN-M02-TRUNCATE-FENCE

- [x] **T-VN-M02-TRUNCATE-FENCE — hard-purge fence의 TRUNCATE 우회를 닫거나, 닫지 않는 이유를 박는다** (2026-09-08 충족, migration 307)

**2026-09-07 실측으로 드러난 구멍이다.** manual Feature hard-purge fence는
`feature.features`의 **BEFORE DELETE row trigger**다. 그런데 같은 표에 BEFORE TRUNCATE
문 트리거가 없다. claim·origin·`ops.domain_commands`에는 no_truncate 트리거가 있다.

**2026-09-08 재실측 — 위 서술의 두 문장이 틀렸다.**

1. ~~`TRUNCATE feature.features CASCADE`가 fence를 통째로 우회한다~~ — **실제로는
   중단된다.** `feature.features`만 TRUNCATE하는 것은 FK 때문에 불가능하고, `CASCADE`가
   끌어오는 30-table 폐포 중 **10개에 켜진 BEFORE TRUNCATE 가드**가 있다
   (`feature_aliases`·`curation_import_rows`·`curation_link_decisions`·
   `theme_feature_candidates`·`curation_cutover_identity_mappings`·
   `curation_import_manual_feature_children`·M05 evidence 넷). **진짜 결함은 다른 것이다** —
   fence는 그 거부에 아무 기여도 하지 않고, 호출자가 받는 진단은
   `T-VN-32C legacy write fence: feature_aliases TRUNCATE 금지`라 manual Feature와 무관한
   이유를 댄다.
2. ~~통합 테스트 24곳이 그 경로에 의존해 무비용이 아니다~~ — **14곳이고, 비용은 0이다.**
   전부 `tests/integration/_db_cleanup.py`를 지나고 그 헬퍼가
   `SET LOCAL session_replication_role = replica`(`:49`)로 돌아 origin 트리거를 전부
   억제한다. 저장소 안에 증거가 있다 — `test_db_cleanup.py`가 위 가드 7개를 포함한
   CASCADE를 **성공으로** 단언하고 CI에서 초록이다.

**원장이 놓친 더 큰 구멍.** `ops.feature_requests`(M04 외부 제출)는 TRUNCATE 가드도
append-only row 가드도 **아예 없다**. `ops.feature_update_requests`·`_datasets`는 DELETE
가드만 있고 TRUNCATE 가드가 없다.

**실제 노출은 훨씬 작다.** 121개 테이블에서 TRUNCATE 권한을 가진 로그인 롤은 컨테이너
superuser 하나뿐이고(`schema.sql`에 `GRANT ... TRUNCATE`가 0건), 그 행위자는
`SET session_replication_role`이나 `ALTER TABLE ... DISABLE TRIGGER`로 **기존 DELETE
fence도 똑같이** 무력화한다. 따라서 origin-enabled 트리거는 보안 바닥을 0만큼 올린다 —
정직한 위협 모델은 적대자가 아니라 **실수**다. 바닥을 실제로 올리는 것은 `ENABLE ALWAYS`
뿐이고, 그것은 `_db_cleanup.py`에 명시 `DISABLE TRIGGER` 네 줄을 요구한다.

**변이 검증의 함정.** "트리거 제거 → red"는 **공허하다** — 이웃 가드가 먼저 raise하므로
지금도 red다. 새 트리거의 **고유 제약 이름/메시지**를 단언해야 한다.

**해제 조건.**

1. 다음 중 하나를 택하고 그 근거를 이 절에 적는다 — (a) BEFORE TRUNCATE 문 트리거를
   더하고 통합 테스트의 정리 경로를 다른 수단으로 바꾼다, (b) 트리거를 더하지 않기로
   하고 "fence는 DELETE 경로만 막는다"를 계약으로 명시한다.
2. (a)를 택하면 우회가 실제로 막히는지 **변이 검증**으로 보인다 — 트리거를 되돌리면
   red가 되어야 한다.
3. 어느 쪽이든 `docs/adr/`의 관련 결정문에 fence의 적용 범위를 한 문장으로 박는다.
4. `ops.feature_requests`를 함께 판정한다 — 위 재실측이 드러낸, 원장이 몰랐던 구멍이다.

**2026-09-08 충족 — (a)를 택했다(migration 307).**

**(a)를 택한 이유는 진단이다.** 재실측이 보인 대로 TRUNCATE는 이미 중단됐고, 결함은
fence가 그 거부에 기여하지 않고 진단이 엉뚱한 이유를 댄다는 것이었다. (b)를 택하면
그 오진이 계약으로 굳는다.

**`ENABLE ALWAYS`다.** origin-enabled 트리거는 보안 바닥을 0만큼 올린다 — TRUNCATE
가능한 로그인 롤은 superuser 하나뿐이고 그 행위자는 `SET session_replication_role` 한
줄로 기존 DELETE fence까지 무력화한다. 정직한 위협 모델은 적대자가 아니라 **실수**이고,
실수를 막는 유일한 변형이 ALWAYS다.

대가인 `_db_cleanup.py`의 명시 DISABLE은 **비용이 아니라 개선**이다. 종전에는 `replica`
한 줄이 무엇을 우회하는지 말하지 않은 채 전부 껐다. 되돌릴 때 `ENABLE ALWAYS`를 써야
한다는 것까지 게이트가 결박한다 — 그냥 `ENABLE`이면 origin으로 내려앉아 남은 세션 내내
우회 가능해지고, 그 상태는 겉보기에 정상이라 아무 테스트도 실패하지 않는다.

**306이 열린 뒤라 이 선택이 가능해졌다.** 이전이라면 더 강한 fence는 "지울 방법이 아예
없다"를 굳히는 것이었다. 이제는 감사되는 삭제 경로가 있으므로 **감사되지 않는 경로만**
막는 것이 된다. 그래서 이 항목과 §T-VN-H49의 purge 판정은 함께 읽어야 한다.

**4항 — `ops.feature_requests`.** TRUNCATE와 DELETE를 막는다. `UPDATE`는 막지 **않는다**
— 라우터가 `status`/`resolved_at`/`resolved_by_actor`를 정당하게 갱신하고
(`_FEATURE_REQUEST_TABLE_ACL`이 그 컬럼만 GRANT한다), 여기서 막으면 M04 해결 경로가
통째로 죽는다. 그 과잉을 막는 축을 따로 뒀다. `feature_update_requests`·`_datasets`는
TRUNCATE만 더한다(DELETE 가드는 이미 있다).

**2항의 함정을 피했다.** "트리거 제거 → red"는 공허하다 — 이웃 가드가 먼저 raise하므로
지금도 red다. 그래서 모든 단언이 **고유 제약 이름**을 본다. 변이 8축 전부 RED
(features_trigger · features_origin_only · requests_truncate · requests_delete ·
update_requests_truncate · delete_guard_overreaches · cleanup_downgrades ·
preflight_rejects_always).

**실측이 잡은 것 셋.** 새 SECURITY DEFINER 함수는 `db.py` startup preflight가 배포를
막았고, 회수는 **소유자만** 할 수 있어 audit writer 소유로 만들어야 했다(기존 guard
주석이 같은 함정을 적어 뒀다). `ENABLE ALWAYS`는 `tgenabled='A'`인데 M05-2 D단계
preflight가 그것을 "꺼짐"으로 읽고 있었다 — `'A'`는 origin보다 **강한** 상태다. 그리고
`test_mois_loader`의 다섯 번째 전역 조회를 찾았다.

3항의 ADR 기재는 ADR-093 개정문(2026-09-08)이 purge 경계를 적으면서 함께 담는다.

**T-VN-M02와 같은 fence다.** `T-VN-M02`의 "지워지지 않는 write"는 바로 이 fence가 유일한
삭제 경로를 거부하기 때문에 생긴다(admin API의 `DELETE`는 soft retire다). (a)를 `ENABLE
ALWAYS`로 택하면 그 되돌릴 수 없음이 **더 강해진다** — 두 항목을 따로 판정하면 안 된다.
