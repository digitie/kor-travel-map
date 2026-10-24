# 파일 레지스트리의 백업 링크 복구

## 실제 원인과 변경

통합 후보 `52949b5f4183bf63593eaabffe562455113451f4`의 격리 실제 UI에서16개 기능
검사는 각각 통과했으나, 파일 상세의 백업 링크를 Next가 RSC prefetch할 때404가 나
전체 실패로 판정했다. 읽기 전용 진단의 phase·RSC/prefetch와 synthetic 파일 경로
지문을 소스에 대조했다. 백업 파일의 `ManagedFileLink.href`는 파일 경로를 상세
route로 붙였지만 프론트에는 `admin/backups/page.tsx` 목록 페이지만 있다.
목록에서 백업을 선택하며 파일별 상세 route·자동 선택 query는 없다.

백업 link의 `rel`·label과 다른 link를 보존하고 `href`만 기존 백업 목록으로 맞춘다.
중첩·공백 파일 경로도 같은 실제 페이지로 연결되는 회귀를 추가했다. DTO/응답 schema,
OpenAPI·TypeScript 타입·프론트 source·DB·동시 쓰기/정책·수집은 변경하지 않는다.
없는 상세 route를 새로 만들거나 prefetch/404 검사를 끄지 않는다.

## 검증과 수용 한계

수정 전 새 회귀는 **1 failed/8 deselected(3.45초)**로 기존 오류를 확인했다. 최종
수정 뒤 router는 **9 passed(5.20초)**, 변경 Ruff·strict mypy1·문서 redaction은
통과했다. 독립2리뷰·정확 CI·실제 UI 재검증은 이 후속 변경의 gate다. 기존 UI의
16개별 PASS와 전체 HTTP404 FAIL, 앞선 행정코드 없는 fixture의 지도 timeout은 각각
구분하여 보존한다. 이 수정은 전체 동시 쓰기/운영 배포 완료 근거가 아니다.
