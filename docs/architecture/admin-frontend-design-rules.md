# admin-frontend-design-rules.md — Admin frontend 디자인 규칙

본 문서는 `kor-travel-map-admin` Next.js admin frontend의 공통 UI 디자인 규칙이다.
2026-06-18 기준 StyleSeed 문서(`https://styleseed-demo.vercel.app/llms.txt`,
`llms-full.txt`)를 참고하되, 본 앱은 모바일 소비자 앱이 아니라 내부 운영자가 반복적으로
쓰는 **데스크톱 우선 운영 콘솔**이므로 아래 로컬 규칙을 우선한다.

## 1. 적용 우선순위

1. 접근성/가독성/운영 안전성.
2. 기존 admin workflow와 Playwright selector 안정성.
3. 본 문서의 StyleSeed 기반 디자인 규칙.
4. 개별 화면의 임시 편의.

StyleSeed 원문이 430px 모바일 앱을 기준으로 제시하는 값은 그대로 복붙하지 않는다.
대신 토큰, 카드 표면, 정보 위계, 상태 표현, 간격 리듬 같은 원칙을 admin 화면에 맞춰
적용한다.

## 2. 핵심 원칙

- **정보는 카드 안에 둔다.** 페이지 배경 위에 metric, table, list, 설명 블록을 직접
  놓지 않는다. 예외는 shell navigation, page header, 지도 canvas처럼 자체 표면인 영역이다.
- **accent 색은 하나만 쓴다.** `--brand`를 active nav, primary action, selected/tint,
  작은 icon badge, progress fill에 제한적으로 사용한다.
- **넓은 색 면을 만들지 않는다.** `bg-brand` 전체 카드, brand gradient, 강한 shadow,
  색이 들어간 shadow는 금지한다.
- **컴포넌트에는 semantic token을 쓴다.** 새 UI에서 hex/color-mix를 직접 넣지 말고
  `bg-card`, `bg-surface-subtle`, `text-text-secondary`, `text-brand` 같은 토큰을 쓴다.
- **숫자는 단위와 함께 보여준다.** KPI 숫자는 `36px : 18px` 또는 `48px : 24px`
  비율로 숫자와 단위를 분리한다. 운영 count는 `개`, `건`, `%`, `ms`처럼 맥락 단위를
  붙인다.
- **같은 카드 패턴을 반복하지 않는다.** KPI 4개라도 보조 요소는 progress, status dot,
  비교 문구, breakdown처럼 변주한다.
- **상태는 색만으로 표현하지 않는다.** `StatusBadge`는 dot + text를 기본으로 하고,
  danger/success/warning/info 색은 작게 쓴다.

## 3. 토큰 규칙

색상 토큰은 `packages/kor-travel-map-admin/frontend/src/app/globals.css`가 정본이다.

| 역할 | 토큰 |
|------|------|
| 브랜드 accent | `--brand`, `text-brand`, `bg-brand`, `bg-brand-tint` |
| 페이지 배경 | `--surface-page`, `bg-surface-page` |
| 카드 | `--card`, `bg-card` |
| 보조 표면 | `--surface-subtle`, `bg-surface-subtle` |
| 구분선/스켈레톤 | `--surface-muted`, `border-surface-muted`, `bg-surface-muted` |
| 텍스트 1차 | `--text-primary`, `text-text-primary` |
| 텍스트 2차 | `--text-secondary`, `text-text-secondary` |
| 텍스트 3차 | `--text-tertiary`, `text-text-tertiary` |
| 비활성 | `--text-disabled`, `text-text-disabled` |
| 아이콘 기본 | `--icon-default`, `text-icon-default` |
| 상태 | `--success`, `--warning`, `--info`, `--destructive` |

새 컴포넌트에서 브랜드 컬러가 필요하면 먼저 token이 있는지 확인한다. 없으면
`globals.css` token을 추가하고, 컴포넌트에는 token class만 사용한다.

## 4. 레이아웃과 표면

- page content의 기본 rhythm은 `space-y-6` 또는 섹션 간 24px 간격이다.
- 반복 카드 grid는 `gap-4` 또는 `gap-6`을 사용한다.
- 단일 정보 블록은 `Card` primitive를 사용한다.
- 카드 안 보조 묶음은 card를 중첩하지 말고 `rounded-xl bg-surface-subtle p-4` 같은
  내부 surface로 표현한다.
- card 안 구분선은 필요한 경우에만 `border-t border-surface-muted`를 쓴다. 페이지 섹션
  사이에 `hr`/`Separator`를 남발하지 않는다.
- mobile width에서는 shell/grid item에 `min-w-0`을 명시해 body horizontal overflow를 막는다.
- 지도 canvas처럼 자체적으로 큰 visual surface인 영역은 카드 안에 억지로 넣지 않는다.
  대신 주변 panel, filter, list는 카드 표면을 따른다.

## 5. 타이포그래피

Tailwind `text-sm`/`text-xs`를 무작정 쓰지 말고, 새 admin surface는 아래 값을 우선한다.

| 용도 | 클래스 |
|------|--------|
| 페이지 제목 | `text-[24px] leading-snug font-bold` |
| 카드 제목 | `text-[18px] leading-snug font-bold` |
| KPI 숫자 | `text-[36px] leading-none font-bold` |
| KPI 단위 | `text-[18px] leading-none font-bold` |
| 카드 본문/list item | `text-[14px] leading-normal` |
| 보조 설명 | `text-[13px] leading-normal text-text-tertiary` |
| label/badge/table head | `text-[12px] font-bold tracking-[0.05em] uppercase` |
| status text | `text-[11px] font-bold tracking-[0.05em] uppercase` |

주의:

- 새 UI에서 `tracking-tight` 같은 음수 letter spacing을 추가하지 않는다.
- 대시보드의 큰 숫자는 같은 크기 단위와 붙여 쓰지 않는다.
- 영어 원문 status/API 용어는 필요한 경우 유지하되, 화면 설명 문장은 한국어를 기본으로 한다.

## 6. Primitive 사용 규칙

- `Card`: 정보 표면의 기본 단위. 직접 `rounded-lg border bg-background p-4`를 반복하지 않는다.
- `Button`: command는 아이콘+텍스트를 우선한다. 주요 action은 기본 44px 높이, 표/compact
  control은 기존 `sm`/`xs`를 쓰되 클릭 가능한 영역을 좁히지 않는다.
- `Badge`: 분류/버전/짧은 label에 사용한다. 상태값은 가능하면 `StatusBadge`를 쓴다.
- `StatusBadge`: 상태 표시의 기본. 색상 + dot + text로 의미를 전달한다.
- `Table`/`DataTable`: table은 카드 안에 두고, header는 uppercase label 스타일을 따른다.
- `Input`/`NativeSelect`/`Textarea`: label은 입력 위에 둔다. 입력 기본 높이는 40px,
  focus ring은 brand token을 사용한다.
- `Alert`: 에러/운영 알림도 카드형 표면으로 보여준다. destructive 색은 텍스트와 작은 아이콘에
  제한한다.

## 7. 대시보드/KPI 규칙

운영 홈이나 summary 화면은 다음 순서를 기본값으로 삼는다.

1. page header card: 현재 화면의 제목, 짧은 설명, 주요 action.
2. KPI grid: 2~4개 핵심 metric. 각 카드에는 숫자+단위와 서로 다른 보조 요소를 둔다.
3. main data card: 최근 job, queue, issue 같은 실제 작업 대상.
4. side/status card: backend/Dagster/provider 상태처럼 보조 판단 정보.
5. lower-priority list/detail card.

KPI grid에서 4개 카드가 전부 같은 구조로 보이면 다시 설계한다. 최소 하나는 progress,
하나는 status dot, 하나는 comparison/breakdown 문구를 사용한다.

## 8. 상태, 로딩, 빈 화면

- loading skeleton도 카드 안에 둔다. 큰 skeleton block을 페이지 배경에 직접 놓지 않는다.
- empty state는 “데이터가 없음”만 쓰지 말고 다음 action이 있으면 함께 제시한다.
- error state는 원인 메시지와 회복 경로를 같이 보여준다.
- loading/error/empty/success는 table, list, detail panel 같은 모든 data surface에 존재해야 한다.

## 9. 금지 패턴

- 컴포넌트 JSX 안 hardcoded hex, brand gradient, colored shadow.
- 카드 안 카드 중첩.
- 페이지 배경 위 bare metric/list/table.
- `text-black`, `bg-black`, 순수 black 계열 색.
- 5개 이상 선택지를 pill toggle로 표현.
- status를 색만으로 표현.
- 새 wrapper/facade성 UI primitive를 만들고 기존 primitive를 우회.
- 모바일에서 body horizontal overflow를 만드는 고정폭 layout.

## 10. 작업 후 확인

Frontend 디자인 변경 PR은 최소 아래를 확인한다.

```bash
npm -w packages/kor-travel-map-admin/frontend run type-check
npm -w packages/kor-travel-map-admin/frontend run lint
NEXT_PUBLIC_KOR_TRAVEL_MAP_API=http://127.0.0.1:12701 \
NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=http://127.0.0.1:12702 \
NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=http://127.0.0.1:12501 \
npm -w packages/kor-travel-map-admin/frontend run build
```

로컬 visual 확인은 적어도 desktop `1280×720`, mobile `390×844`에서 수행한다. backend가
떠 있지 않아도 loading/error 상태에서 카드 구조와 overflow는 확인할 수 있다.
