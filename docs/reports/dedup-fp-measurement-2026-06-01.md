# dedup false-positive 측정 + ADR-016 가중치 검토 (2026-06-01)

Sprint 4a 마무리 항목 — dedup scoring(ADR-016)의 false-positive를 대표 라벨
평가셋으로 측정하고, 가중치(0.45/0.35/0.20)·임계값(0.85/0.65) 조정 필요 여부를
판단한다.

## 1. 방법

- **scoring**: 실제 `core.scoring.score_pair` + `classify_decision`(코드 변경
  없이 그대로 채점). 회귀 가드는 `tests/unit/test_dedup_fp_measurement.py`.
- **평가셋(14쌍)**: true duplicate 7 + distinct 7. 모두 **blocking 범위 내**로
  구성 — ADR-016 DB blocking이 `ST_DWithin(coord, 100m)` + 같은 `bjd_code` +
  같은 `kind`로 사전 필터하므로, 멀리 떨어진 쌍은 애초에 후보가 아니다. 따라서
  distinct 라벨은 "**가까이 있는 별개 장소**"(같은 건물/인접) — 실제 운영에서
  scoring이 마주하는 어려운 케이스.
- **지표**: AUTO 임계(0.85, 자동 병합)와 MANUAL 임계(0.65, 검토 큐 진입) 각각의
  precision/recall.

## 2. 결과 — 채점표

| label | dup | score | name | spat | cat | decision |
|-------|-----|-------|------|------|-----|----------|
| exact-same | ✓ | 1.000 | 1.00 | 1.00 | 1.00 | auto_merge |
| spacing | ✓ | 1.000 | 1.00 | 1.00 | 1.00 | auto_merge |
| paren-branch | ✓ | 1.000 | 1.00 | 1.00 | 1.00 | auto_merge |
| space-mid | ✓ | 1.000 | 1.00 | 1.00 | 1.00 | auto_merge |
| brand-suffix | ✓ | 0.974 | 0.94 | 1.00 | 1.00 | auto_merge |
| coord-30m | ✓ | 0.820 | 1.00 | 0.49 | 1.00 | manual_review |
| cat-mismatch | ✓ | 0.800 | 1.00 | 1.00 | 0.00 | manual_review |
| pharmacy-suffix | ✗ | 0.780 | 0.67 | 0.80 | 1.00 | manual_review |
| mart-suffix | ✗ | 0.780 | 0.67 | 0.80 | 1.00 | manual_review |
| diff-cafe | ✗ | 0.762 | 0.47 | 1.00 | 1.00 | manual_review |
| church-suffix | ✗ | 0.719 | 0.67 | 0.62 | 1.00 | manual_review |
| diff-food | ✗ | 0.550 | 0.00 | 1.00 | 1.00 | keep_separate |
| diff-retail | ✗ | 0.419 | 0.00 | 0.62 | 1.00 | keep_separate |
| diff-name-samecat | ✗ | 0.370 | 0.00 | 0.49 | 1.00 | keep_separate |

## 3. 지표

**AUTO 임계(≥0.85, 자동 병합):**
- 예측 5건(all true) → **precision 100% / false auto-merge 0건**.
- 이것이 가장 중요한 안전 속성 — 운영자 개입 없이 병합되는 경로에 오류 0.

**MANUAL 임계(≥0.65, 검토 큐 진입):**
- 후보 11건 = true 7 + distinct 4 → **precision 63.6% / recall 100%**.
- true duplicate 7건 전부 큐에 진입(놓침 0). distinct 4건이 큐에 함께 진입(FP).

**distinct 7건의 분포:** keep_separate 3 / manual_review 4 / auto_merge **0**.

## 4. 발견

1. **오토머지 오류 0** — 가까운 별개 장소(같은 건물·같은 카테고리)도 AUTO 임계를
   넘지 못한다. 자동 병합은 안전하다.
2. **manual FP 4건의 원인**:
   - **카테고리 접미사 공유** — `약국`/`마트`/`교회` 2글자 접미사가 name_sim을
     0.67로 끌어올린다(`현대약국`↔`종로약국`). 같은 건물(spatial 0.8) + 같은
     카테고리(cat 1.0)와 결합해 0.72~0.78.
   - **짧은 일반 브랜드명의 우연한 jaro 겹침** — `스타벅스`↔`투썸플레이스`
     name_sim 0.47 + 같은 좌표/카테고리 → 0.76.
   - 모두 **AUTO 임계 아래** → 검토 큐로 라우팅되어 운영자가 reject(설계 의도).

## 5. 권고 — 가중치/임계값 **변경 없음**

ADR-016 가중치(0.45/0.35/0.20)와 임계값(AUTO 0.85 / MANUAL 0.65)을 **유지**한다.

- **안전성 검증됨**: 자동 병합 precision 100%, true duplicate recall 100%. 위험한
  방향(오토머지 FP)의 오류가 0.
- **검토 큐 noise는 설계 의도**: 가까운 동일-카테고리 별개 장소가 manual_review로
  가는 것은 정상 — 그게 큐의 존재 이유다. 운영자가 reject하고, 확정 병합은
  `krtour-map dedup-merge`로 적용한다.
- **접미사 stripping은 권하지 않음(현 시점)**: 4건의 manual FP를 줄이려 카테고리
  접미사(`약국`/`마트`…)를 name 정규화에서 제거하면, 반대로 **접두사 충돌 FP**가
  생긴다 — `강남약국`↔`강남마트`가 접미사 제거 후 둘 다 `강남`이 되어 name_sim
  1.0. `core.scoring._NAME_SUFFIX_TO_STRIP`이 **빈 튜플로 의도적 보수 설정**된
  이유(코드 주석)와 일치. 이득(노이즈 감소)보다 위험(새 FP)이 커서 현 시점 보류.

## 6. 한계 / 후속

- 본 평가셋은 **대표 큐레이션 셋**(운영자 라벨 실데이터 corpus 아님). production
  에서는 `ops.dedup_review_queue`의 운영자 accept/reject 누적분으로 **실 FP율**을
  재측정해야 한다(reject/전체 비율 = manual FP율의 직접 추정). MOIS Step A bulk +
  cross-provider 적재가 큐를 채우면 그 데이터로 재검토 → 그때 임계 미세조정 또는
  ADR-016 amendment 판단.
- 회귀 가드: `tests/unit/test_dedup_fp_measurement.py`가 (1) 오토머지 FP 0,
  (2) true-dup recall 100%, (3) manual precision floor 0.55를 CI에서 지속 검증.

## 7. 결론

ADR-016 scoring은 현 가중치/임계값에서 **안전하고 적절**하다(자동 병합 오류 0,
true duplicate 누락 0). 검토 큐의 false-positive는 가까운 동일-카테고리 별개
장소이며 운영자 검토로 해소되는 설계 범위 내. **가중치 조정 불필요** — 운영
데이터 누적 후 실 FP율로 재검토.
