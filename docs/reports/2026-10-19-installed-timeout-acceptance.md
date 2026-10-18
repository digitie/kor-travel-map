# T-MAP-02 현재 설치 세대와 Geo 인증 경로 수용

timeout 구현 #1325의 머지523d98cc는 운영 source e937b38d의 조상이다.
기존 소스 감사와 이번 현재 설치 파일 SHA256 대조를 결합해 이미 배포된 코드를 확인했다.
제품·컨테이너·설정·키는 변경하지 않았고 불필요한 재배포를 수행하지 않았다.

## 배포 세대 판정

원래 해제 조건은 머지 뒤 첫 prod 배포 generation 기록이었다. 과거 첫 배포의 UUID는
회수하지 못했고 현재 컨테이너에도 generation/pinset 라벨·환경키가 없다.
따라서 과거 UUID를 새로 만들거나 소급 증명하지 않는다. 이번 수용에서는 현재 설치
세대를 source revision + 이미지 digest + CID + StartedAt의 묶음으로 명시한다.
사용자의 남은 Track 수용 완료 지시에 따라 이 현재 설치 증거로 T-MAP-02를 닫는다.
원래 시점의 UUID 미회수와 현재 구현 설치 확인은 다른 사실이다.

Map API와 CS의 revision은 e937b38d176cfeb759daca629395f51c1a6a4d5f이며,
각 시작시각은 2026-10-17T01:00:39.277910995Z와 01:00:51.291295732Z이다.
각 이미지/CID는 [공개 증거](2026-10-19-installed-timeout-acceptance.json)에 보존했다.
양쪽 geocoding.py·settings.py·providers/kor_travel_transport.py 전체 hash가
현재 main의 동일 파일과 일치했다. 이는 세 파일의 직접 검증이며 이미지 전체 소스
정합이나 모든 호출 지점의 실측 검증으로 확대하지 않는다.

connect 기본4초, geo read/write/pool10초, transport30초인 구현은 이미 존재한다.
앞선 소스 감사는 생성 지점13개(geo10/transport3)의 팩토리 사용과 구현 조상을 확인했다.
이번 검증이 실제 네트워크 무응답에서4초 종료를 측정한 것은 아니다.

## 실제 소비자 인증 확인

컨테이너 내부의 기존 env에서 Geo origin이 현재 Odroid 정본인지와 키 존재를 확인한 뒤,
공개 좌표1개로 reverse를 각1회 호출했다. 실제 키·호스트값·좌표·주소 응답·키 hash는
공개 증거에 넣지 않았다. 재시도0, 직렬3요청, timeout10초였으며 모두 HTTP200/OK다.

| 직접 소비자 | 호출 결과 | 소요 |
| --- | --- | ---: |
| PinVi API | 200 / OK | 673.16ms |
| Map CS | 200 / OK | 53.29ms |
| Map API | 200 / OK | 53.76ms |

각 호출 전후 CID/image/PID/StartedAt/RestartCount가 같다. 같은 좌표 반복으로
서버 cache가 데워질 수 있으므로 이 수치를 성능 비교로 쓰지 않는다. 이는 실제 env
인증 경로 확인이며 각 앱의 사용자 API·UI 전체 경로를 실행한 E2E는 아니다.
서버의 정상 캐시·접근 감사까지 부작용0이라고 주장하지 않는다.

PinVi CS에는 Geo URL/key env가 없고 직접 API 설정 모듈도 없었다.
검사한 apps/etl 소스에는 kor_travel_geo/KorTravelGeo 직접 사용이 없으므로
직접 Geo 소비자 시험 대상에서 제외했다. PinVi API 키를 CS에 복사하지 않았다.
PinVi 제품 변경이 없어 별도 PinVi PR은 만들지 않는다.

## 남은 외부 운영 조건

daemon OFF 정책을 유지하며 sensor를 켜지 않았다. 실제 변경 token 전량 재계획,
MOIS 전체 수집, Odroid 전원 단절 drill은 이 수용과 다르다.
T-MAP-02 문서가 원래도 별도 외부 추적으로 둔 장애 drill을 완료로 표시하지 않는다.
과거 baseline/noop UI 및 격리 변경·복구 시험은 각 기존 증거를 따른다.

문서만 변경하며 사용자 지시에 따라 CI는 생략한다. 두 독립 리뷰 후 PR로 병합한다.
