# ADR-122 — weather 예보는 `since` 증분을 지금 Valkey 세대에 병합하고, 하루 한 번 전량으로 다시 맞춘다

- 상태: proposed (2026-11-10, 구현 PR과 함께. 배포 뒤 단기·외부 증분 run 시간과 전량/증분 값 대조를 실측하면 accepted)
- 날짜: 2026-11-10
- 결정자: Claude(설계·구현), 소유자 지시("Map 예보 적재를 증분으로, 정확성이 속도보다 먼저")
- 관계: **ADR-114 W3의 "받을 때는 전량 — `since` 증분은 쓰지 않는다"를 대체**한다(나머지 W3 — ETag·410·422·503
  재시도·요청 계수 — 는 그대로). ADR-114 D3(세대 교체 CAS)·D4(거부 기준)를 그대로 쓰되 D4는 전량에만 건다.
  ADR-104·105(Map은 KMA를 직접 적재하지 않고 PG weather feature도 없다)는 그대로다 — 이 ADR은 Valkey 상태만 다룬다.

## 컨텍스트

- `weather_state_forecast_*`(W3 `short`·`external`·`ultra_short`·`mid`)는 run마다 weather
  `/v1/service/exports/forecasts` 전량을 받는다. 단기는 1,168 파일·1.15 GB·134만 point, 외부는 929 파일·531 MB를
  weather가 odroid eMMC에서 읽어야 하고(cold 약 1,174초·674초), Map run은 1,500·1,200초 상한에서
  1,514·1,201초에 ReadTimeout으로 죽었다(2026-11-10).
- weather W3는 이미 `since`와 `meta.next_since`를 준다. 다만 그 계약은 **완전한 증분이 아니다**(아래 "원천 계약").

## 원천 계약 (weather main `3bcda7e` 소스 기준 — `export_forecasts.py`·`export_mid_reader.py`·`export_heads.py`·`export_inventory_selection.py`)

1. **`since`·`next_since`의 뜻.** `next_since`는 snapshot을 얼린 순간의 **publication clock**(행 하나,
   `weather_export_publication_clock`)이다. 승인 generation의 `created_at`이 head 공개 transaction 안에서 그 clock 값으로
   찍히고(`GREATEST(clock + 1µs, now)` — 단조, 동시 공개는 행 잠금으로 직렬), reader는 head vector와 clock을 같은
   REPEATABLE READ에서 읽는다. 그래서 늦게 commit된 공개도 다음 `since`에 걸린다. `next_since`는 manifest 하나의 값이라
   모든 페이지가 같다.
2. **`since`가 고르는 것.** manifest의 승인 scope(KMA 격자·외부 cohort·inventory namespace) 중 `published_at > since`인
   scope를 **통째로** 다시 낸다 — 그 scope의 위치마다 (위치, provider) 묶음 전체(scalar patch가 아니다). 중기는
   (육상, 기온) 쌍의 `max(published_at)`으로 위치마다 고른다. `since`가 아직 발급되지 않은 watermark면 422다.
3. **순서.** 페이지는 manifest scope 순 → 위치 id 순이다. 계약으로 약속된 순서는 아니다(중기는 chunk 순으로 다시
   정렬한다). Map은 순서에 기대지 않는다.
4. **시간 필터.** 매 페이지가 그 요청 시각 `now`로 `target_at > now`만 낸다. metric은 미래 point가 있을 때만 나오고,
   미래 point가 없는 위치는 빼고 페이지를 `stale`로 표시한다. `known_at`은 지난 point까지 포함한 최댓값이다.
5. **tombstone은 없다.** since 응답에는 제거가 실리지 않는다. 다음은 전량에서는 사라지지만 증분에는 흔적이 없다:
   (a) 승인 만료(`source_expiry` — 원천이 그 위치를 주지 않은 지 오래) (b) 위치 비활성화·격자 재편으로 scope에서 빠진
   위치 (c) provider·dataset이 선택에서 빠짐(설정·재배포) (d) 외부 cohort 퇴역 (e) **재공개된** scope에서 미래 시각이
   하나도 없는 위치 — weather는 그 위치를 빼고 페이지를 `stale`로만 표시하므로(어느 위치인지 알리지 않는다) 증분에서는
   재공개 자체가 보이지 않는다. weather 자신도 이 공백을 열린 과제로
   적어 두었다(weather `docs/tasks.md` W-MAP-08 "since delta tombstone(F14/F25)", `docs/design/map-service-exports.md` §3.3
   "시간 since만 쓰면 group 삭제를 놓친다").
6. **snapshot 재발급·fallback.** 같은 선택(style·since·provider 서명)의 같은 manifest는 15분 handle을 재사용·연장한다.
   새 원천이 준비되지 않으면 **같은 선택의 직전 snapshot**을 stale로 다시 낸다 — `since`가 새 값이면 그런 직전 snapshot이
   없어 503이다. provider 서명이 바뀌면 선택이 달라 cursor는 422(도중)지만, **`since` 값 자체는 무효가 되지 않는다** —
   새로 선택된 provider의 옛 scope는 증분에 오지 않는다(위 5(c)의 반대 방향).
7. **전량 재동기화 신호는 없다.** weather는 "전량으로 다시 받으라"를 알리지 않는다. Map이 볼 수 있는 것은 422(아직 발급되지
   않은 watermark)와 `next_since`의 역행뿐인데, **둘 다 DB 복원을 믿을 만하게 알리지 못한다** — clock은 벽시계
   (`greatest(clock_timestamp(), …)`)라 복원 뒤 첫 공개가 곧바로 Map의 cursor를 넘어서고, 그 뒤 증분은 복원 이후 공개만 낸다.
   더해지는 것도 놓칠 수 있다: 다시 켜진 위치(옛 inventory 행·옛 `published_at`)와 새로 선택된 provider의 옛 scope는 증분에
   오지 않는다. 그래서 **weather DB 복원·provider 설정 변경 뒤에는 운영자가 예보 job 넷을 `full_resync: true`로 한 번씩 돌린다.**
8. **증분 503.** weather는 얼리지 못하면 같은 선택(**`since` 포함**)의 직전 snapshot을 stale로 낸다. 새 `since`에는 그것이 없어
   503이다(전량이면 직전 전량 snapshot을 200으로 받는다). 중기는 수집 run이 도는 동안 `unconfirmed_sources`로 그렇게 된다.

## 결정

1. **cursor는 세대 meta에 있다.** 예보 세대 meta(`…:{ds}:{gen}:meta`)에 `sync_mode`(`full`|`delta`)·`sync_cursor`(그
   세대까지 반영한 `next_since`)·`full_synced_at`(사슬을 시작한 전량 run의 시작 시각)·`row_duplicates`를 더한다. cursor는
   세대와 **같은 CAS 교체**로만 전진하므로 "세대는 옛것인데 cursor만 앞선" 상태가 없다. 새 키·PG migration은 없다(meta hash에
   필드가 느는 것이라 키 버전도 그대로 — ADR-114 W2와 같은 판단).
2. **증분 = 지금 세대 + 증분 → 새 세대, 원자 교체.** run은 잠금 → 지금 세대 meta → `since=sync_cursor`로 끝까지 받기 →
   지금 세대 값 전부를 읽어(`HSCAN`) → 병합 → 새 세대를 build TTL로 쓰기 → Lua CAS 교체 순서다. 교체는 `require_base`로
   **병합의 기준으로 읽은 세대가 아직 current일 때만** 일어난다(어긋나면 아무것도 쓰지 않고 `state_swap_conflict`). 세대
   키는 여전히 불변이고, 읽는 쪽은 교체 전 옛 세대·교체 후 새 세대만 본다.
3. **병합 규칙(전량과 같은 값).** 증분에 온 (위치, provider) 묶음은 지금 세대의 같은 묶음을 **그대로 바꾼다**(weather가
   그 묶음 전체를 다시 낸다 — metric·시각 삭제도 그대로 반영된다). 오지 않은 묶음은 weather가 지금 낼 모양으로 만든다:
   `target_at <= now`를 떼고, 떼었으면 남은 값이 모두 null인 metric을 빼고(값 배열의 null = point 없음), 남는 시각이 없으면
   묶음을 빼고, 묶음이 없는 위치를 뺀다. 위치 안 묶음은 provider 순으로 둔다(전량도 같게 바꿨다 — 원천 순서에 기대지 않는다).
4. **증분을 버리고 같은 run에서 전량을 받는 경우**(`resync_reason`): cursor 없음·전량 사슬이 아님(`no_cursor`·`not_loaded`)·
   주기 도래(`periodic`, 기본 24시간 − 15분 여유)·운영자 요청(`full_resync` run config·`allow_shrink`)·증분 끔(`delta_disabled`)·
   기준 세대에 중복 행(`base_row_duplicates`)·첫 페이지 422(`cursor_rejected`)·`next_since` 없음·역행(`no_next_since`·
   `cursor_regressed`)·증분 묶음의 `published_at <= since`(`delta_not_after_since`)·증분 안 중복(`delta_duplicates`)·
   지금 세대보다 오래된 묶음(`published_at_regressed`)·기준 세대 값 개수가 meta와 다르거나 모델과 맞지 않음
   (`base_count_mismatch`·`base_unreadable`·`base_mismatch`). 증분이 503(페이지 재시도 소진)이면 원천 계약 8 때문에
   세대·cursor를 그대로 두고 run은 성공한다(`unchanged=delta_unavailable` — 전량이었어도 이미 병합한 것 이하를 받았다).
   410·401·404·그 밖의 계약 위반은 지금과 같은 실패 분류다. 예보 전량은 `If-None-Match`를 보내지 않는다(304는 cursor를
   다시 잡지 못한다).
5. **거부 기준(D4)은 전량에만.** 증분 교체는 거부 기준을 보지 않고 `recent_counts`에도 넣지 않는다 — 증분이 줄일 수 있는
   것은 시각 경과뿐이고, 기준 창은 원천 전량의 크기만 담아야 한다. 전량 재동기화는 지금처럼 80%(단기 65%) 기준을 받는다.
6. **주기 전량.** `KOR_TRAVEL_MAP_WEATHER_FORECAST_FULL_RESYNC_HOURS`(기본 24, 0이면 증분 끔 — 되돌리기). 위 원천 계약 5·7의
   차이는 이 주기 안에서만 남는다: **증분 사이에 생긴 제거·놓친 추가·DB 복원으로 잃은 공개는 최대 하루 동안 Map에 남거나
   빠질 수 있다**(제거된 묶음은 시각이 지나면 더 일찍 사라진다). 이것이 받아들인 차이이고, weather가 아래 "weather에
   요청"을 내면 없앤다. 주기 전량이 실패하는 동안은 증분도 멈춘다(전량이 성공할 때까지 매 run 전량) — run 실패가 경보다.
7. **run 상한.** 단기 3,600초·외부 2,400초로 올린다 — 증분 run은 짧지만 첫 적재·주기·증분 거절 뒤 전량이 같은 run에
   들어야 한다. lock TTL(상한 + 660초)은 3시간 발화 간격 안이다.

## 정확성 검사(drift 방지)

- **등가 시험.** `tests/unit/test_weather_forecast_delta.py`가 weather `since`·시간 필터 규약의 모형 위에서 "직전 전량 +
  증분 병합 = 지금 전량"을 **저장 바이트**로 본다: 재공개(metric·시각 삭제 포함)·새 provider·scope에 위치 추가·시각
  경과(`target == now` 경계, 모든 시각이 지난 묶음·위치)·증분 사슬 5단·무작위 40 seed. 같은 파일이 tombstone 없는 제거와
  계약 5(e)는 증분이 고치지 못함을 고정한다. `tests/integration/test_valkey_weather_state.py`가 실제 Valkey에서 증분 세대와 같은 시점
  전량 세대의 값이 같고, 기준 세대가 바뀌면 교체가 거절되고, 증분이 거부 기준 창을 건드리지 않음을 본다.
- **run마다.** 기준 세대 값 수 = meta `count`, 값이 모델과 맞음, 증분 묶음 `published_at > since`, 지금 묶음보다 새롭거나
  같음, (위치, provider) 중복 없음, 모든 페이지 `next_since` 같음, `next_since >= since` — 하나라도 어긋나면 전량.
- **주기 전량**이 남은 차이(계약 5)를 하루 안에 지운다.

## 결과

- 정상 run은 바뀐 scope의 artifact만 weather가 읽는다(단기 3시간 주기면 대개 그 회차 격자). 하루 한 번은 지금처럼 전량이다.
- Valkey 쓰기량은 같다(증분도 세대 전체를 새로 쓴다 — 단기 약 15 MB). 증분 run은 지금 세대를 한 번 더 읽는다.
- 잃는 것: 위 결정 6의 최대 하루 지연. 증분 교체는 거부 기준이 없어, weather가 예보 지평선보다 오래 공개를 멈추면 시각
  경과로 세대가 비어 간다(전량이었어도 weather가 미래 시각 없는 위치를 빼거나 503을 낸다 — 같은 결과). 거부 기준 창
  (`recent_counts` 6개)은 이제 전량만 담아 약 6일 치 최대값이다. 세대 meta `source_status`는 증분 페이지의 값이라, 전량이었으면 "미래 시각 없는
  위치를 뺐다"로 `stale`이 됐을 run이 `ok`일 수 있다(값은 같다 — Map이 그 묶음을 스스로 뺀다).

## weather에 요청(이 PR 밖)

1. **since 응답의 제거 신호.** 가장 단순한 형태: 모든 W3 응답 `meta`에 **전량 기준 멤버십 digest**(얼린 manifest의
   `(location_id, provider, published_at)` 정렬 집합의 digest — 시간 필터 전, `since`와 무관). artifact를 읽지 않고 manifest만으로
   계산된다. Map은 병합 결과의 같은 digest와 비교해 다르면 그 run에서 전량을 받는다 — 그러면 결정 6의 지연이 없어진다.
   시간 필터 **전** 집합이어야 계약 5(e)(재공개됐지만 미래 시각이 없어 빠진 위치)도 잡힌다 — Map 쪽 값에는 그 위치의 새
   `published_at`이 없어 digest가 달라진다. 대안은 명시 tombstone 목록(W-MAP-08)과, 시간 필터로 뺀 (위치, provider)를 meta에
   싣는 것이다.
2. **clock epoch.** `meta`에 publication clock의 출처 식별자(DB 복원·재설치마다 바뀌는 epoch)를 실어 주면 Map은 cursor 옆에
   두고 바뀌면 전량을 받는다(원천 계약 7 — 지금은 운영자 수동 `full_resync`).
3. **확인 질문.** (a) `value_number`·`value_text`가 둘 다 null인 point가 W3에 나올 수 있는가(나오면 결정 3의 "모두 null인
   metric 빼기"가 그 metric을 잘못 뺀다). (b) 한 style에서 같은 (위치, provider)가 두 scope에 들 수 있는가(들면 전량의 첫 행
   선택을 증분이 재현할 수 없다 — Map은 그 경우 전량만 쓴다).

## 기각한 대안

- **Valkey 안에서 `COPY` 후 바뀐 필드만 `HSET`.** 쓰기는 줄지만 세대 개수 검사(CAS의 `HLEN = meta.count`)를 쓰기 전에 알 수
  없고, 시각 경과로 빼야 하는 묶음을 고르려면 어차피 값을 읽어야 한다. 단기 세대 15 MB는 읽고 다시 써도 run 시간에 비해 작다.
- **증분을 읽을 때 합치기(세대 여러 개를 겹쳐 읽기).** 읽는 쪽이 사슬을 따라가야 하고 교체 원자성(D3)이 깨진다.
- **증분 run에도 거부 기준.** 증분은 원천 집합 크기를 말하지 않는다 — 시각 경과로 준 개수를 "원천이 줄었다"로 오판한다.
