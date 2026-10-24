# Geo stamp writer 권한 경계 — migration421

## 고정 시점과 완료 범위

이 문서는 일반 runtime의 stamp raw 쓰기를 회수하고 좁은 SD를 통해서만 쓰게 하는 선행 구현을 정리한다. 실제 SH collector 배선·운영 활성화·전체 동시쓰기 완료가 아니다. 부모 #1392와 문서 #1393의 main41150 원문을 보존해 합성했다. 이 문서 고정 시점의 최종 정확 HEAD CI·두 독립 코드 리뷰·fresh UI 수용은 별도이며 PR #1394 본문과 감사 원장을 따른다. broad T-CWRITE 체크는 미완이다.

승인된 [구현 전 SQL 계약 원문](2026-10-25-stamp-writer-sql-contract.md)은 SHA256 `0de8cfcf60270fc4d0e9904e36bb0599c1b5dcb3d4f50a719e0366c77dfb1e42`로 보존했다. 원문의 d476/419 참조는 설계 시점이다. main에 먼저 들어온 PG transport 퇴역419를 보존하고 EX 적재를420, 이 구현을421로 옮겼다. 아래 현재 구현·비용 보강이 설계 당시 legacy 정렬 구현을 대체한다. 다른 SH 정렬 잠금과 검증 의미는 유지한다.

## DB가 강제하는 세 진입점

| 진입점 | 강제하는 조건 | 허용하는 쓰기 |
| --- | --- | --- |
| `feature.upsert_provider_geocode_stamps_ex(uuid[],text[],text,text)` | protocol EX→global→epoch, typed shape, bulk active 교집합의 기존420 full-context 전수 검증 | 기존 legacy mapping의 모든 행과 same-TX `now()`·FK·행 수를 보존한 UPSERT |
| `feature.lock_scoped_provider_geocode_stamps(uuid,uuid,text,text,jsonb)` | 적용 중 SH attempt의 owner/epoch/동일 물리 TX·input/manifest/완전 dependency·active revision·primary place/source·기존 stamp evidence와 정렬 행 잠금 | 쓰기0, preflight count |
| `feature.reobserve_scoped_provider_geocode_stamps(uuid,uuid,text,text,jsonb)` | 같은 조건 재검사와 actual accepted head==입력 record key | 기존 stamp의 `stamped_at=now()`만 |

SH는 정확8필드·최대2730행·총1MiB이며 정본 `se_`+64hex/`sr_`+20hex를 검증한다. preflight 이전에는 새 source가 head가 아닐 수 있어 current equality를 요구하지 않는다. source DML 뒤 writer가 입력 record key의 실제 채택을 검증한다. ID/version/data/outcome 변경·신규 stamp·다른 Feature 쓰기는 SH에 허용하지 않는다. 실제 source-link union과 완전 manifest가 필요하며 prefix/session.info/호출 스택은 권한이 아니다. normalizer/지원 외 projection·retire0은 후속 wrapper의 별도 조건이다.

일반 runtime의 stamp table 권한은 SELECT뿐이다. I/U/D/TRUNCATE/FOR UPDATE는42501이며 broad EX를 쥐어도 같다. state procedure owner에 S/I/U만, 공개 세 SD에 runtime EXECUTE만 명시한다. private policy SELECT·raw ops·새 role/context table는 추가하지 않는다. 기존 caller와 SD의 유한 GUC cap을 늘리지 않으며 SH→EX 업그레이드는23514다. legacy2731행을 실제 검사했으며 SH2730/1MiB 제한을 legacy 전체 입력에 전파하지 않는다.

stamp I/U의 전용 SECURITY INVOKER trigger는 실제 current_user가 기존 NOLOGIN state owner인지 검사한다. active 보호는 legacy SD의 applying EX full-context 또는 SH SD의 완전 DB 검증에 남긴다. DELETE는 기존 공유 SECURITY DEFINER reject/비활성 FK cascade 의미를 유지한다. 기존 공유 reject 전체를 SI로 바꾸지 않는다.

같은 canonical service login은 명시 SET ROLE로 schema/state owner에 들어갈 수 있다. 이는 기존 restricted-migrator 관리 경계이며 차단한 것으로 세지 않는다. 일반 runtime current_user와 명시 고권한 역할을 구분하며 동일 session_user의 의도로 둘을 구별하지 않는다. 이 기능은 superuser/명시 관리자에 대한 sandbox가 아니다.

## 설치와 기존 경로

`418_creation_protocol → 419_retire_pg_transport_values → 420_exclusive_provider_refresh → 421_stamp_writer_boundary` 단일 lineage다. migration은 기존 OFF0 또는 검증된 active50만 허용해 active면 원자적으로51로 재배선한다. exact relation/name/정의 SHA/enabled를 검증하고 partial·drift를 거부한다. schema CREATE의 기존 권한과 역할/GUC·receipt/head/graph를 보존하며 forward-only다. 신규 stamp trigger는 OFF migration에서 설치하지 않고 첫 activation이51개를 설치한다.

기본OFF는 SH planning/새 scope 시도0을 뜻한다. legacy가 raw INSERT에서 SD로 바뀌므로 모든 SQL·role·비용이 그대로라고 하지 않는다. noactive는 bulk 조회1회이고 N별 full-context 호출0이다. active는 각 target의 기존420 context를 생략하지 않는다. 새 SQL은 기존 mapping의 모든 항목을 처리하지만 SQL 행 순서를 공개 보장하지 않는다. SH stamp의 canonical 정렬 잠금은 바꾸지 않았다. legacy EX에는 추가 Feature FOR KEY SHARE 선취득을 하지 않는다. protocol/global과 active begin의 기존 Feature closure 잠금·FK/CONFLICT 검사는 유지한다.

## 비용 반증과 UPSERT 한 문장 계획 보강

동일 고정 a3c4 harness는 canonical owned PG/runtime에서 EX/global을 이미 보유한 뒤 stamp0/1/3000행의 insert·재관측을 각3회 측정하고 rollback한다. whole collector/SH/ARM 수치가 아니다. 앞선 역할·검증을 삭제해 비용을 해결하지 않았다.

| 고정 실험 | 3000 insert PG CPU 중앙값(core-ms) | 3000 재관측 PG CPU 중앙값(core-ms) | 해석 |
| --- | --- | --- | --- |
| parent1be 장수 backend A/B/B/A의 A6개 | 111.534 | 93.9975 | 기존 raw 기준 |
| d588 장수 backend B6개 | 140.9465 | 158.1255 | 실제 회귀 원본 보존 |
| 정렬만 제거한0db 별도3개 | 116.490 | 140.948 | 재관측 약50% 회귀가 남음 |
| 함수 전체 `force_custom_plan` owned 진단3개 | 224.534 | 96.385 | 재관측 회복/insert 악화로 제품 채택하지 않음 |
| UPSERT만 `EXECUTE … USING` owned 진단3개 | 110.060 | 92.245 | 둘 다 기준 수준; 아직 최종 제품 비용 수용 대체가 아님 |

서로 다른 시각의 진단 중앙값만으로 모든 원인을 확정하지 않는다. fresh clone 첫 호출 결과로 장수 backend 회귀를 지우지 않는다. auto_explain의 nested ModifyTable/plan rows는 원인 구간용이며 계측 시간을 최종 속도로 쓰지 않는다. 함수 전체 GUC는 FK 내부 계획에도 영향을 줄 수 있으므로 제품에 넣지 않았다.

현재 보강은 고정 qualified UPSERT만 dollar-quoted `EXECUTE`와 typed `$1`/`$2` 및 `$3`/`$4`의 `USING`으로 실행한다. SQL/identifier를 데이터로 조합하지 않는다. 검증·active context/epoch·권한·SH는 그대로이며 즉시 `GET DIAGNOSTICS ROW_COUNT`로 반환한다. 함수나 caller의 `plan_cache_mode`는 바꾸지 않는다. owned 진단은 원 pg_get_functiondef/owner/ACL/proconfig를 모두 복원하고 exact CID를 정리했다.

singleton의 절대 비용은 숨기지 않는다. parent ABBA1행 insert0.530/reobserve0.4925core-ms에 비해 해당 UPSERT-only 진단은1.099/1.474core-ms였다. 0행 SQL/PG CPU/WAL0은 유지했다. 최종 고정 제품의 canonical18 반복·active1/100 context 호출 수/비용은 별도 수용이며 전체 CPU/ARM 감소를 주장하지 않는다.

## 실제 검증과 초기 실패 보존

- d588: 기존 EX18+stamp49+DB22+ACL19=108 PASS/68.26초, oracle/metadata2 PASS/22.50초, lint373 PASS/기존6skip. 이 수치는 새 제품 결과와 합산하지 않는다.
- 0db: EX18+J stamp/업그레이드54+oracle/metadata2=74 PASS/107.35초. record1 SKIP/13.69초는 PASS가 아니다.
- 현재 후보: EX18+stamp/업그레이드54+DB22+ACL19+oracle/metadata2=115 PASS/108.39초다. 이전 세대 결과와 합산하지 않는다. 새 oracle 기록1 SKIP/14.16초는 산출 절차이며 PASS가 아니다.
- 최초 FK 합집합104 PASS/4 FAIL은 같은 module DB에서 기존44가 활성 guard를 설치한 뒤 새 FK raw DELETE가23514로 정상 거부된 fixture 격리 오류다. 새 FK5만 별도 OFF owned DB로 옮겼고 기존44/제품/공유 fixture는 유지했다.
- J의 실제 parent420 활성50→421 신규5는 정상50→51과 partial·definition drift·disabled·old0/new1의 실패 원자성/ACL/head/receipt·samebackend role/GUC를 검사한다. 과거 parent ACL은 old1be 원문과 현 reconcile+역사적 stamp I/U2 복원의 전체 catalog 동등 audit로 확인했다. CI에 옛 Python/Git source를 의존시키지 않는다.
- 첫 glibc5 setupERROR는 extension `_st_concavehull` 차이와 name 타입의 긴 signature 절단이었다. 양 UNION을 text로 바로잡고 실제63자 초과 identity를 검사하며 audit된 immutable2image의 전체 ACL golden만 허용한다. unknown image는 거부한다. J914 신규5는 alpine5 PASS/17.91초·glibc5 PASS/15.68초이며 제품 guard 실패로 세지 않는다.
- audit matrix의 private-policy SELECT42501은 제품 권한의 정상 거부였다. 감사 helper만 기존 schemaowner observer로 옮겼고 새 GRANT로 우회하지 않았다. 원 실패/cleanup 원장과 성능 악화 진단은 보존했다.

각 source 고정·실 import/hash·raw 로그·O_EXCL JSON과 exact owned CID/UUID/runtime backend 정리 근거를 감사 원장에 남긴다. source 각 세대/별도 실행은 중복 합산하지 않는다. 운영 DB·HTTP·정책 활성화는0이다.

## 최종 고정 전 정산

최종 제품 코드는 집중115 PASS/108.39초·lint373 PASS/기존6 SKIP/28.32초·문서4 PASS/0.98초·Ruff·strict mypy3·import4 contracts를 통과했다. 기록1 SKIP/14.16초는 별도다. J XML에서 관측한 정확3 CID가 NotFound이고 runtime backend54건이0이며 scalar label 잔여0을 확인했다. 정확 최종 HEAD의 CI/UI/독립 리뷰와 최종 비용 gate는 PR본문/감사 원장으로 분리하며, 이를 문서에 사후 추가하려고 기능 source를 바꾸지 않는다.

## 남은 gate

1. 최종 제품 noactive18 및 active1/100 실제 applying EX/완전 manifest 비용·context 호출 수. trial별 fresh plan/rollback/cancel, 별도 deferred 검증 비용과 실제 한정 범위를 기록한다. rollback만으로 deferred constraint CPU/commit 전체를 측정했다고 하지 않는다.
2. 정확 최종 HEAD CI·두 독립 FULL/delta 코드 리뷰·fresh API/UI·설치/배포 수용. 원 raw 실패를 삭제하거나 무코드 rerun으로 우회하지 않는다.
3. 실제 SH wrapper의 저장 normalizer/R1/R2·provider projection와 operator effective 분리·숨겨진 원천 변경의 후보 갱신·accepted head·동일 typed Geo evidence·dataset 전체 retire0 조건.
4. 기존 capture count/hash는 stamp를 포함하지 않는다. A3 attempt의 stamp 지문은 completed replay용이며 후속 SERIALIZABLE child/root seal의 stamp 증거라고 세지 않는다. 새 영속 인계 계약은 별도다.
5. 실제 두 provider/두 dataset DML 중첩, worker/Geo pool/취소·사망·idle TX 복구, 5000행 입력/영속 artifact/운영 활성화. file_sources 업로더를 새로 구현하지 않았고 broad T-CWRITE 완료를 표시하지 않는다.
