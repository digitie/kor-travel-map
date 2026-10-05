<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie) -->

# Map·PinVi builtin Docker frontend 독립 FULL 연속 리뷰 B

**고정 소스·계약 FULL PASS. 새 P0/P1/P2/P3 finding 없음.** 이번 판단은 API·ETL header 변경 및 전체 manifest의 연속 source review이다. 신규 실제 Docker build/운영 pair 재구축/live 성공을 판정한 것은 아니다. 이전 실제 build 실패도 성공으로 바꾸지 않는다.

## 실행·격리·고정 SHA

- 실행 ID: J-BUILTIN-FULL-20261006-0058369c.
- UTC 2026-10-05T15:08:53.338281+00:00 ~ 2026-10-05T15:10:26.671856+00:00 (KST 2026-10-06 00:08:53~00:10:26).
- Common base7dc1d6dda955b9b836cb3f24d6fd5bcd37fabe52 → actuala960bdb114d99a2ac1b9608a77b240635806e551.
- Map basea46d7b92c0e727805348e20d60fe188592e16477 → actual1ba6ef4c52f64200e3bc3e9a4fee1dd5f8d4e77e.
- PinVi base07cfef222c56d7e648c81b017aa8ffe4ccd1c386 → actual0058369c778f8c3357ee393e12e3447d7975cc1f.
- Manifest map-pinvi-builtin-reviewed-manifest.json SHA256 954edf0fe117091c4d39c9fbe1e4d797981c73ade359f74eaeb0d67184dbe866.
- Common35/Map61/PinVi15 총111개 exact blob SHA256와 각 base→candidate 변경 파일 목록을 고정 Git 객체에서 직접 확인해 모두 일치했다. docs/reviews/**는 내용 없이 digest만 확인했다. Peer raw·통합 verdict는 읽지 않았다.
- 본인 scratch /home/digitie/.cache/james-map-pinvi-builtin-20261006에 대상 Dockerfile 고정 사본 및 verification.json만 보존했다. 제품·운영·foreign 설치·사용자 dirty 원본을 수정하지 않았고 N150에 접속/실행하지 않았다.

## FULL 범위와 검증 재사용

Build/config 변경은 문서 closure 면제 대상이 아니다. 이전 전체 Common HTTP/복구/UI/소비자 FULL 검토와 새로운 PinVi Docker frontend 경계 검토를 결합한 FULL 연속 리뷰이다.

이전 PinVi2a36e897→0058369c 변경 파일은 정확히 apps/api/Dockerfile, apps/etl/Dockerfile, docs/journal.md 세 개뿐이다. 두 Dockerfile은 처음 두 줄을 제외한 본문 bytes가 완전히 동일하다. API 본문 SHA256 f7bd66d9bfb147f7592909317d79e0fcbc36876675de1ad19ff87b0dfad070b6, ETL 본문 SHA256 b62db3357f2ccc43c7c80ba7b4f60e77b8e16aced4acafcc2d34eb6221d9396b.

따라서 FROM/설치/UV lock/빌드 constraint/COPY/entrypoint/health/provenance label, 앱·ETL Python·UI·DTO·OpenAPI·M05 계약·vendor/lock는 전부 동일하다. Common과 Map도 이전 승인 객체 자체와 같다. 이 불변 영역에 한해서 본인의 기존 실제 CLI·HTTP·consumer·fixture 검증을 재사용한다. 기존 테스트를 이번에 재실행했다고 집계하지 않는다. 이전 markers 원문 SHA256 5508bcd71d59d78a00350114915fc5f6f6e05b5ef27a823774abba1ecb0d63ae도 불변 확인했다.

## 직접 수행한 정적 공격·확인

1. 전체111 blob/변경 목록/actual commit 직접 검증.
2. 두 Dockerfile 전체 내용을 고정 객체에서 읽고 header 이후 동일성을 assert했다. 사용 instruction은 ARG/CMD/COPY/ENV/EXPOSE/FROM/HEALTHCHECK/LABEL/RUN/WORKDIR이며 multistage 및 COPY --from 사용은 표준 문법이다. RUN/COPY/ADD에 --parents/--mount/--device/--link/--exclude 등 확장 flag가 없고 heredoc/labs 기능도 사용하지 않는다.
3. 두 파일에 syntax directive가 없는 것을 확인했다. Builtin frontend 사용을 방해할 source-local parser 지시자가 남지 않았다.
4. 반대로 web Dockerfile은 기존 digest 고정 syntax와 COPY --parents를 그대로 유지한다. API·ETL 변경이 web labs 요구를 깨지 않는다.
5. Peer evidence를 제외한 고정 PinVi source 전체에서 BUILDKIT_SYNTAX 참조를 검색했으며 0개였다. API/ETL CI docker build 경로도 별도의 해당 override를 전달하지 않는다. 외부 Manager/운영 harness invocation을 이번에 실행하거나 강제 검증한 것은 아니다.
6. Journal은 실패 당시 이전 여섯 서비스 보존, “version 독립 재현성”을 주장하지 않는 점, builder 버전 실증과 새로운 build/live gate를 명확히 분리한다. 이전 외부 frontend 실패를 성공으로 승격하지 않는다.

이번 EXECUTED는 Git hash/byte 검증과 정적 계약 assert이다. 새 단위·Docker·브라우저 테스트를 수행했다는 수치로 집계하지 않는다.

## Builtin 선택·override·재현성 경계

Docker 공식 설명상 BuildKit은 builtin Dockerfile frontend를 포함하며, BUILDKIT_SYNTAX build argument로 외부 frontend를 선택할 수 있다. 외부 frontend의 장점은 여러 builder에서 같은 구현을 사용할 수 있다는 것이다. [Docker 공식 frontend 문서](https://docs.docker.com/build/buildkit/frontend/) (2026-10-06 확인).

따라서 이번 선택은 표준 API·ETL에 불필요한 외부 labs frontend 실행 의존을 제거하는 것으로 타당하다. 그러나 Dockerfile header가 없어도 외부 invocation이 --build-arg BUILDKIT_SYNTAX=...를 주면 외부 frontend가 다시 선택될 수 있다. 이 변경은 그 override를 금지하는 보안 정책이 아니다. Builtin 구현은 사용 builder/BuildKit 버전에 결합되므로 동일 source만으로 모든 builder의 동작·이미지 byte 재현성을 보증하지 않는다.

실제 재구축 증거에는 builder/BuildKit 버전과 frontend override 미사용을 확인해야 한다. 지금 소스의 표준 문법과 고정 FROM/의존성 계약은 유지되지만, 이전 gRPC 종료의 단일 근본 원인이 확정되거나 새 builtin 경로가 실제 host에서 통과했다고 판단할 근거는 이번 리뷰에 없다. 이를 source finding으로 확대하지 않고 운영 build gate의 명시적 제한으로 남긴다.

## 기존 disposition와 NOT_RUN

J-HEALTH-SCHEMA-P2-01(P2) 및 J-STANDALONE-P2-01(P2)은 동일 Commona960에서 기존 FIXED 유지. 이전 consumer/HTTP findings도 불변 source에 기존 FIXED 유지한다. 새 finding은 없다.

새 exact candidate CI 최종 결과, Docker parser/build 실제 실행, 운영 disk preflight/이미지 정리, pair 재구축·전환, N150 브라우저 live E2E, production Dagster child/job 복구는 **NOT_RUN**. Root가 전달한 실제 실패/기존 서비스 보존·디스크 부족은 작성자의 관측이며 본인 직접 실행 수치에 합산하지 않았다. 디스크 guard 거절을 새 제품 성공이나 운영 완료로 표시하지 않는다.

**최종: 고정 소스·공용 계약 FULL PASS. 실제 build/CI/운영/live gate는 별도로 미완료.**
