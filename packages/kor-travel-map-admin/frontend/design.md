# Design — kor-travel-map admin console

A locked design system for this app (`packages/kor-travel-map-admin/frontend`). Every page redesign reads
this file before emitting code. Do not regenerate per page — extend or amend this file when the system
needs to grow. Source: `hallmark audit` 2026-08-18 (`docs/reports/hallmark-audit-admin-frontend-2026-08-18.md`)
→ `hallmark redesign` multi-page flow. Stamp every restyled file:
`/* Hallmark · genre: editorial-utilitarian · macrostructure: <family> · design-system: design.md · designed-as-app */`

## Genre
**editorial-utilitarian** — an internal ops console where hierarchy is carried by type, hairlines and
alignment, not by shadow and card chrome. Dense data first; the page is a working surface, not a landing.
Editorial rules that transfer: hairline rules over card borders, tinted (never pure) paper/ink, one accent
hue at ≤ 5 % of any viewport, quiet motion, verbs over adjectives. Editorial rules that do NOT transfer:
serif display, drop caps, asymmetric prose columns, enrichment of any tier.

## Macrostructure family (app pages only — there are no marketing/content pages)
Base shape for every route: **Rail-Workbench** — `AdminShell` side rail (N3) → flush header band (h1 +
breadcrumb + ≤ 1 primary / ≤ 2 secondary actions) → toolbar (FilterBar) → dense list (DataTable) → optional
inspector rail (right, fixed `--rail`). Containment is at most ONE layer per region: a `SectionCard` or a
`Card` may hold content, never another card/box. Variation knobs (the only allowed differences between pages):
- **list**: toolbar → DataTable (+ CursorPager/OffsetPager) → inspector rail on row selection.
- **detail**: header band → two-column (main flush sections separated by hairlines · right rail `DetailList`).
- **map**: header band → map canvas full-bleed → floating *flat* legend/status strip (no framed panel).
- **form** (settings / new): header band → single column, `FormField` stack, one save row at the end.
- **dashboard** (home): header band → typographic stat strip (`StatStrip`: number + label, hairline
  separated, no icon tiles) → recent activity list.
- **login**: single centered column, wordmark, one form, no card frame; hairline above the footer line.
Banned everywhere: card-in-card, icon-tile KPI grids, floating shadowed header cards, dashed-border
centered empty states, glass/gradient/blob, emoji, hover-elevation on non-interactive containers.

## Theme — custom, anchored on the existing brand green (token NAMES are kept; values are OKLCH)
Light (default). Numbers verified for WCAG AA where used as text on paper/tints.
- `--surface-page`   oklch(97.8% 0.003 128)   paper (unchanged)
- `--surface-subtle` oklch(96.7% 0.006 138)   paper-2 (toolbars, zebra, hover rows)
- `--surface-muted`  oklch(92.5% 0.010 141)   rules / dividers (`--border`)
- `--card`           oklch(99.2% 0.002 140)   panel surface (was pure white → tinted)
- `--text-primary`   oklch(30% 0.006 157)     ink (deepened for 15px body; was 36.4%)
- `--text-secondary` oklch(48% 0.012 159)     ink-2 (labels, captions) paper 6.10:1 · card 6.35:1
  (AA 4.5:1 통과. 직전 문서의 "≥ 7:1"은 실측이 아니었다 — AAA가 필요하면 L을 내리고 네 표면을 다시 잰다)
- `--text-tertiary`  oklch(54% 0.012 154)     paper 4.73:1 · subtle 4.58:1 · card 4.92:1 (명목 56%는
  paper 4.35 / subtle 4.21로 AA 미달이라 54%로 내렸다 — `globals.css`가 정본)
- `--text-disabled`  oklch(79% 0.012 154)     non-text use only (never as the only cue)
- `--icon-default`   oklch(54% 0.012 154)     의미를 나르는 아이콘(= text-tertiary와 같은 값;
  paper 4.73:1 · card 4.92:1). 장식 아이콘은 `text-text-tertiary`, 상태 아이콘은 상태 토큰을 쓴다.
- `--brand`          oklch(51.4% 0.081 169)   accent (unchanged) — links, primary CTA fill, active nav mark
- `--brand-hover`    oklch(46% 0.085 169)
- `--brand-tint`     oklch(95.2% 0.013 172)   selected row / active nav wash (opaque)
- `--brand-foreground` oklch(99% 0.002 140)
- `--success` oklch(46.9% 0.087 149) · `--success-tint` oklch(95% 0.03 150)
- `--warning` oklch(50.9% 0.103 71)  · `--warning-tint` oklch(96% 0.035 80)
- `--info`    oklch(50% 0.16 258)     · `--info-tint`    oklch(95.5% 0.025 255)   (was blue-500 = 3.7:1)
- `--destructive` oklch(51.4% 0.167 27) · `--destructive-tint` oklch(96% 0.03 25)

**Hairlines — 2종이고, 섞어 쓰지 않는다.**
- `--border` = `--surface-muted`  *장식* hairline: 표 구분선, 패널/카드 경계, 비대화 컨테이너.
  대비 요건 없음(정보를 나르지 않는다). 실측은 light card 1.22:1 · page 1.17:1 · subtle 1.13:1,
  dark 1.29 · 1.41 · 1.25 — **조작 가능한 요소(버튼·pager·입력)의 경계로 쓰면 1.4.11 미달이다.**
  장식선을 컨트롤에 재사용하지 않는 이유가 이 숫자다.
- `--control-line` oklch(61% 0.012 145)  **조작 가능한 요소의 경계 전용** — input · textarea ·
  native-select · checkbox · combobox 껍데기 · outline 버튼. `--input`(shadcn 이름)이 이 값을
  가리키므로 컴포넌트는 계속 `border-input`을 쓴다. WCAG 1.4.11(non-text contrast) 대상이라
  인접 배경 대비 **3:1 이상**: card 3.69:1 · `--surface-page` 3.54:1 · `--surface-subtle` 3.43:1
  · `--surface-muted` 3.03:1. (직전 값 oklch(89% 0.01 145)는 card 1.36:1 / page 1.30:1 / subtle
  1.26:1로 전부 미달 — 컨트롤이 배경에 녹아 보였다.)
  Dark: oklch(58% 0.012 145) → card 3.96:1 · page 4.33:1 · subtle 3.85:1 · muted 3.07:1
  (직전 oklch(36% 0.012 145)는 card 1.56:1). 값을 바꿀 때는 이 네 표면 전부에서 3:1을 다시 계산한다.
- 세 번째 선은 없다. 다만 **선택/활성 상태의 brand 테**(`border-brand`)는 hairline이 아니라
  *상태를 나르는 잉크선*이라 §CTA voice가 따로 정의한다 — `--brand`는 네 표면 모두 4.35:1 이상이다.

**Lines · overlay · aliases**
- `--focus`   oklch(45% 0.09 169)     opaque focus outline, offset 2px — page 6.66:1 · card 6.93 ·
  subtle 6.45 · muted 5.70 (dark 10.26 · 9.38 · 9.13 · 7.28). 직전 문서의 5.4:1은 실측과 달랐다.
- `--overlay` oklch(30% 0.006 157 / 0.45)  the ONLY allowed alpha colour (dialog scrim)
- `--compare-a` oklch(51.4% 0.081 169) · `--compare-b` oklch(50% 0.16 258)  dedup/compare marker pair
- shadcn aliases (`--background/--foreground/--primary/--ring/--card/--popover/--muted/--accent/--input`)
  stay defined and mapped in `@theme`, but component code speaks the project vocabulary above.
  `--input` is not a colour of its own — it is the alias of `--control-line`.
- Dark: `.dark` block keeps the same names with dark values (kept in sync, no toggle mounted).
- Rule: **no alpha as palette** (`/10`, `/20`, `/50` on colours) — use the opaque `*-tint` tokens; no raw
  hex/oklch/rgb outside `globals.css`; marker colours in map code read `--compare-a/b`.

## Typography
- Sans (body, UI, headings): **Pretendard Variable** — `--font-sans`, loaded via the `pretendard` npm
  package dynamic-subset CSS (Korean glyph coverage; Geist Sans is REMOVED). Weights 400 body · 500 UI
  labels/buttons/nav · 600 h2/section titles/table headers · 700 h1 only.
- Mono (IDs, paths, JSON, hashes, coordinates): **Geist Mono** — `--font-mono` via `next/font/google`.
  Always `tabular-nums` for numeric columns.
- Scale (`@theme` tokens; no `text-[Npx]` anywhere):
  `--text-2xs` 12px · `--text-xs` 13.5px · `--text-sm` 15px (body) · `--text-md` 17px · `--text-lg` 20px
  · `--text-xl` 24px (h1) · `--text-2xl` 30px (dashboard stat only). Line-heights 1.5 body, 1.25 headings.
- No uppercase/small-caps transforms on Hangul; Latin eyebrows may use `tracking-wide` at 12px 500.
- Headings are roman; emphasis by weight or accent, never italic.

## Spacing · shape · size
- 4-pt scale via Tailwind spacing (`gap-2`=8, `p-3`=12, `p-4`=16, `gap-6`=24, section `py-6`).
- Radii: exactly two — `--radius-control` 6px (buttons, inputs, badges, tabs) · `--radius-panel` 8px
  (Card/SectionCard/dialog/popover). `--radius` alias = 6px. Nothing at 10/14/18/`rounded-2xl`.
- Control heights: `--control-h` 36px (`h-control`) · `--control-h-sm` 30px (`h-control-sm`). Every
  **standalone** control — 툴바 버튼, 폼 입력, 셀렉트, 다이얼로그 액션 — uses one of the two.
- **Micro-control 예외 (닫힌 목록).** 다른 컨트롤 *안에* 있거나 표 헤더 셀의 타이포그래피에
  얹히는 in-flow 어포던스는 두 높이를 쓰면 셀을 밀어내므로 아래 4개만 예외로 허용한다.
  글자는 `text-2xs`, 히트 타깃은 `before:`/`after:` 의사요소 inset으로 ≥ 24px까지 넓힌다.
  **새 높이를 추가하지 않는다.**
  - DataTable 정렬 헤더 버튼 `h-7`(28px) — `<th>` 안의 라벨 자체가 버튼이라 30px면 헤더 행이
    본문 행보다 높아진다. `h-control-sm`으로 통일하고 싶으면 헤더 행 높이를 함께 재조정할 것.
  - `Input`의 `file:` 버튼 `h-6` · MultiFilterCombobox 칩 `h-6` · 칩 제거 버튼 `size-5`(+`before:-inset-1`)
  - `Checkbox` `size-4`(표준 체크박스 크기, 히트 타깃은 `after:-inset-2` → 16 + 8×2 = **32×32**)
- Rail: `--rail` 22rem (right inspector) · sidebar 16rem.

## Depth
- rest = hairline(`border-border`)만, 그림자 없음. 그림자는 오버레이 전용 — `--shadow-elevated`
  (popover/menu) · `--shadow-modal`(dialog). `--shadow-card*`는 정의만 남기고 기본 사용처가 없다.
- 비대화 컨테이너에 hover elevation을 주지 않는다. containment는 언제나 한 겹(§Macrostructure).

## Motion
- Easings: `--ease-out` cubic-bezier(0.16, 1, 0.3, 1) · `--ease-in` cubic-bezier(0.7, 0, 0.84, 0).
- Durations: `--duration-fast` 100ms (hover/colour) · `--duration-base` 150ms (overlay enter,
  opacity+scale .98) — utility 이름은 `duration-fast`/`duration-base`. (`--dur-*`는 이 문서의 옛
  이름을 받아 주는 alias일 뿐, 정본은 `--duration-*`다.)
- Animate `opacity`/`transform` only; `transition-[color,background-color,border-color,box-shadow]` for
  state colour changes. **대상을 열거하지 않는 전환 유틸은 전부 금지** — `transition-all`,
  맨 `transition`, 그리고 `transition-colors`. Tailwind v4는 `transition`/`transition-colors`의
  전환 목록에 **`outline-color`를 포함**하므로(v4 upgrade guide) 이 둘을 붙인 요소는 포커스 링 색이
  `duration-fast`(100ms) 동안 페이드된다 — 아래 "즉시"가 깨진다. Focus ring appears instantly
  (outside transitions; §Focus).
- `prefers-reduced-motion: reduce` → all spatial motion collapses to ≤ 150ms opacity crossfade (global rule).
  - **예외: 로딩 스피너는 계속 돈다** (`[data-slot="button-spinner"] svg`, Sonner의 loading 아이콘).
    회전이 "지금 처리 중"을 알리는 유일한 시각 신호이기 때문이다 — `Button loading`은 라벨을
    `opacity-0`으로 감추므로 스피너가 멈추면 정지 상태와 구분되지 않는다. 킬스위치에서 빼되
    회전을 1.6s로 늦춰(기본 1s) 전정기관 부담만 줄인다. 전역 `*` 규칙과 specificity로 경쟁하므로
    `animation-duration`과 `animation-iteration-count`를 둘 다 다시 선언해야 한다.
  - 반대로 `Skeleton`은 콘텐츠 자리표시(장식)라 컴포넌트에서 `motion-reduce:animate-none`으로 완전히
    끈다. 로딩 여부는 감싸는 영역의 `aria-busy`가 알린다. 판단 기준: **애니메이션이 사라졌을 때
    상태를 알 수 없게 되면 살리고, 자리표시일 뿐이면 끈다.**
- Live-updating regions (ops streams/logs) never re-order or flash on update.

## Focus
- 링은 `globals.css`의 `@layer base` 한 곳에서만 발행한다:
  `:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px }`. 컴포넌트가 아무것도
  선언하지 않아도 링을 받는다는 뜻이다. 대비는 light page 6.66:1 · card 6.93 · subtle 6.45 ·
  muted 5.70 / dark 10.26 · 9.38 · 9.13 · 7.28 — 네 표면 모두 1.4.11의 3:1 위.
- **링은 전환하지 않는다.** v4의 `transition`/`transition-colors`는 전환 목록에 `outline-color`를
  포함한다. 포커스를 받는 요소에는 반드시 열거형(`transition-[color,background-color,border-color]`)
  을 쓴다(§Motion).
- **링을 흐리지 않는다.** `opacity`는 요소 전체(=자기 outline·border 포함)를 합성한다. root에
  `opacity-55`를 걸면 링이 light page 6.66 → **2.57:1**, card 6.93 → 2.61, subtle 6.45 → 2.54
  (dark 3.89 / 3.77 / 3.73)로 떨어지고 `border-input` 경계도 page 3.54 → **1.87**, card 3.69 → 1.90
  (dark 4.33 → 2.16, 3.96 → 2.11)이 된다. 1.4.11의 "비활성 컴포넌트" 면제는 native `disabled`에만
  해당하고, `aria-disabled`/`aria-busy`는 **포커스를 유지하는 상태**라 면제 대상이 아니다.
  → 흐림은 라벨·아이콘을 감싼 **자식 래퍼**에만 건다(§States).
- **링을 끄는 수단은 `focus-visible:outline-0` 하나뿐이다.** `outline-none`은 `outline-style: none`과
  함께 v4 내부 변수 `--tw-outline-style`을 `none`으로 박는다. 같은 요소의 `outline-<n>` 유틸은
  style을 `var(--tw-outline-style)`에서 읽으므로 `outline-none focus-visible:outline-2`처럼 짝을
  맞춰 적어도 링은 **영영 안 그려진다**(twMerge도 둘을 다른 그룹으로 봐서 지워 주지 못한다).
  `focus-visible:outline-0`은 `outline-width: 0`만 바꾸고 style/색은 건드리지 않으며,
  `focus-visible:outline-2`와 같은 twMerge 그룹이라 CSS 순서에 기대지 않는다.
- **끄는 자리는 두 종류뿐이고 목록은 닫혀 있다.**
  1. **대체 링이 있는 컨트롤** — 부모 래퍼가 `has-[input:focus-visible]:outline-*`로 링을 대신
     그리는 자리. 안쪽 요소에 `focus-visible:outline-0` + 이유 주석. 현재 유일한 사례는
     `MultiFilterCombobox` 안쪽 `Input`.
  2. **프로그램 포커스 전용 컨테이너** — Tab 순서에 없고(`tabIndex={-1}` 또는 오버레이 라이브러리의
     autofocus) 앱이 대신 포커스를 옮기는 큰 상자. 사용자가 키로 이동한 게 아니라 링이 "어디로
     갔는지"를 알리지 못하고, 페이지/패널 폭의 2px 테두리만 새로 그려진다(패널 경계는 이미
     `border-border` + `shadow-modal`이 그린다). 정체는 `role` + 제목 + scrim이 알린다.
     **닫힌 목록은 정확히 4개**이고 넷 다 단일 공용 primitive라 그 자리에 `focus-visible:outline-0`
     + 이유 주석을 둔다(호출부에서 바로 보이도록 — base에 allowlist를 따로 두지 않는다):
     `DialogContent`(`ui/dialog.tsx`) · `AlertDialogContent`(`ui/alert-dialog.tsx`) ·
     `PopoverContent`(`ui/popover.tsx`) · `AdminShell`의 `<main tabIndex={-1}>`(skip link 대상,
     `components/admin-shell.tsx`). 목록을 늘리려면 여기부터 고친다.
  - **예외가 아닌 것**: roving tabindex 목록 행(`SelectableRow`의 `tabIndex={-1}`)·`TabsContent`처럼
    키보드가 실제로 도달하는 요소. `[tabindex="-1"]`을 통째로 끄면 안 되는 이유가 이것이다.
- 링을 요소 안쪽에 그려야 하는 경우(표 헤더·목록 행처럼 이웃 셀이나 컨테이너에 잘리는 자리)만
  `focus-visible:-outline-offset-2`를 쓴다. 색은 항상 `outline-focus`.
- base가 이미 링을 발행하므로 컴포넌트가 같은 레시피를 다시 적는 것은 중복이다. 로컬 outline
  유틸이 정당한 경우는 셋뿐 — inset 변형 · 폭 0으로 끄기 · 부모 `has-` 링.

## States (rest · hover · active · focus · disabled · busy)
- **흐림(`opacity-55`)은 root가 아니라 자식에 건다.** 수치와 근거는 §Focus. 라벨·아이콘을 감싼
  자식 래퍼에만 걸어 링·컨트롤 경계·사유 텍스트는 100 %로 남긴다
  (`selectable-row.tsx`의 content/trailing, `button.tsx`의 `[data-slot="button-label"]`,
  `ui/tabs.tsx`의 `[data-slot="tabs-trigger-label"]` 레시피). 흐림이 필요한 새 컨트롤은 라벨 래퍼를
  하나 두고 `group-disabled/…:opacity-55 group-aria-disabled/…:opacity-55`를 거기에 건다.
- `disabled`(native)와 `aria-disabled`(진행 중·차단이지만 포커스 유지)는 **항상 두 벌을 같이**
  선언한다. 색만 다른 게 아니라 도달성이 다르다 — 후자는 포커스·`title`·스크린리더 접근을 유지한다.
- 진행 중(busy)은 **누른 그 컨트롤에** 표시한다: `Button loading`(= `aria-busy` + `aria-disabled`
  + 스피너 오버레이), 페이지 스피너 금지. 한 그룹의 여러 버튼이 같은 mutation을 공유하면 `loading`은
  **실제로 눌린 버튼에만** 준다 — 그룹 첫 버튼에만 달면 스피너가 엉뚱한 버튼에 뜬다.
  `loading` 없이 `disabled={isPending}`만 주면 native disabled가 포커스를 뺏어 **진행 중에 키보드
  위치가 사라진다**(pager에서 특히 치명적: 다음 페이지를 연속으로 넘길 수 없다).
- 못 쓰는 컨트롤은 이유를 말한다(`disabledReason`/`title` + 인라인 한 줄). 사유 텍스트는 흐리지
  않는다 — 흐려진 글자로 이유를 설명할 수는 없다.

## Microinteractions stance
- Silent success: mutations that re-render their own region show no toast; toasts only for cross-page
  effects (Sonner without `richColors`, tones from tokens).
- Destructive/irreversible actions: `useConfirm` with a verb label (`보관`, `삭제`, `취소`) and one line of
  consequence copy; non-irreversible actions never confirm.
- Optimistic update + Undo where the write is idempotent; otherwise loading state on the trigger
  (`Button loading`), never a page-level spinner for a row action.
- Tooltip: hover 800ms / focus 0ms (`HelpTip`); hit targets ≥ 24px.
- Disabled controls state their reason (`title` + inline note), never colour-only.

## CTA voice
- **경계 규칙(모든 variant가 여기서 파생된다).** 조작 가능한 컨트롤은 *채움*이 인접 배경 대비
  3:1 이상이면 경계 없이 두고, 그렇지 못하면 hairline 경계를 그린다(WCAG 1.4.11). 중립 컨트롤의
  경계는 `border-input`(= `--control-line`), brand tint를 채운 **선택/활성 상태**는 `border-brand`
  (상태 자체가 정보이므로 brand 잉크로 표시). 장식용 `border-border`는 컨트롤에 쓰지 않는다
  (light card 1.22 · page 1.17). 모든 variant가 `border border-transparent`를 깔고 있어 테를
  켜고 꺼도 폭이 흔들리지 않는다.
- Primary: solid `--brand` fill, `--radius-control`, 500, verb label (`저장`, `적용`, `가져오기`); one per band.
  채움 자체가 light page 5.08 · card 5.29 / dark 8.92 · 8.15이라 경계를 그리지 않는다.
- Secondary: outline — `border-input` + `bg-card` + ink text. 경계 대비 light card 3.69 · page 3.54 ·
  subtle 3.43 · muted 3.03 / dark 3.96 · 4.33 · 3.85 · 3.07 이라 hover(`surface-subtle`)·
  active(`surface-muted`)에서도 3:1을 지킨다. 모든 secondary CTA와 pager 버튼이 이 레시피다.
- `secondary`(brand-tint 채움)는 **토글의 눌린 상태 전용**이다. tint는 네 표면 모두
  light 1.08~1.12 · dark 1.27~1.42라 채움만으로는 상태를 알릴 수 없으므로 `border-brand`로 테를
  세운다(brand vs card 5.29 · page 5.08 · subtle 4.93 · muted 4.35 / dark 8.15 · 8.92 · 7.94 · 6.33,
  자기 채움 대비 light 4.73 · dark 6.26). 꺼진 짝은 `outline`이라 토글 내내 경계가 유지되고 채움과
  잉크만 바뀐다 — `field.tsx`의 `has-data-checked:border-brand`, `Checkbox`의
  `data-checked:border-brand`와 같은 레시피다. **단독 CTA로는 쓰지 않는다**(밴드에 primary가 없으면
  `outline`, 정말 하나를 앞세워야 하면 `default`).
- ghost: 경계도 채움도 없이 라벨로만 식별되는 유일한 tier. 그래서 **컨테이너가 이미 경계를 가진 자리
  안**(툴바·표·행)에서만 쓰고, 헤더 밴드나 폼의 단독 액션으로는 쓰지 않는다.
- Destructive: `--destructive` fill only inside confirm dialogs; in-page it is the outline recipe
  (`border-input` + destructive 잉크, hover에서 `border-destructive`).
- Links in prose: `--brand` underline on hover; links styled as buttons take the button recipe (no underline).

## Status colour semantics (single tone table — `src/lib/status-label.ts`)
`success` = 활성/완료/ready · `warning` = 검토 필요 / 사람의 결정 대기 / quarantine / 저하 ·
`destructive` = **실제로 잘못된 것만** (실패/blocked/dead-letter/거부) · `info` = draft/candidate/
valid(informational) + 기계가 진행 중인 상태(queued/running/…) · `neutral` = archived/disabled/unknown/
종료된 중립 상태. Every badge, dot, option and column reads this table; enum values are never rendered raw.
- **정상 취소는 `neutral`이다** (`cancelled`/`canceled`). 운영자가 직접 누른 취소의 *성공* 경로라
  실패가 아니다. 빨갛게 칠하면 `cancel_failed`(= 취소가 실패한 destructive)와 구분이 사라지고,
  /ops/pipeline 실행 목록에서 실패 건수를 눈으로 세는 스캔이 망가진다.
- **같은 한글 라벨은 같은 tone만 가진다.** 한 화면에 두 축의 배지가 함께 뜨면 같은 글자가 다른 색으로
  보여 색의 의미가 무너진다. 충돌하면 tone(의미의 정본)이 아니라 **라벨을 좁힌다**:
  "대기" = `pending`(사람의 결정 대기, warning) 전용 → 기계 큐 `queued`는 "실행 대기"(info) ·
  "진행중" = `in_progress`(기계 진행, info) 전용 → Feature event 축 `ongoing`은 "행사중"(success) ·
  "확인됨" = `acknowledged`(사람이 인지, info) 전용 → 결과 확정 `confirmed`는 "확인 완료"(success).
  (`pending`/`acknowledged` 문자열은 live e2e 계약이라 그쪽을 고정했다.)
  현재 134개 키 전부가 이 규약을 만족한다 — 한 라벨이 두 tone을 갖는 경우 0건이며
  `src/lib/status-label.test.ts`가 이를 회귀로 잠근다.
- **같은 상태는 화면 어디서나 같은 문자열이다.** 배지뿐 아니라 KPI/`StatStrip` 라벨·필터 옵션·
  컬럼 값이 모두 `statusLabel(status)`를 거친다. 라벨을 손으로 적으면 같은 축이 자리마다 다른
  단어로 보인다(예: `queued`를 KPI에선 "대기", 같은 화면 실행 행 배지에선 "실행 대기"로 적던
  /ops/pipeline). 화면에 뜨는 상태 문구의 정본은 `src/lib/status-label.ts` 하나뿐이다.

## Copy
- Buttons/nav are verbs or task nouns already in use (중복 검토, 보강 검토, 정합성 점검). No `확인` on a
  confirm — name the action. Errors: what · why · what to do (`AppErrorPanel`). Empty states: left-aligned,
  one sentence + one action, no icon-above-title tile. Null glyph `—` (not `-`), separators `·`.
- Never invent metrics: loading shows `—`, never a false 0. **값이 없으면 단위도 함께 사라진다** —
  `— 개` / `— 건`은 "단위가 붙을 만한 값이 있었다"는 가짜 신호이고, 스크린리더는 "대시 개"로 읽는다.
  단위(`개`·`건`·`%`·`ms`)는 값이 실제로 있을 때만 붙인다. 로딩 중이면 Skeleton이 자리를 지키고
  감싸는 영역의 `aria-busy`가 상태를 알린다.

## 금지 패턴 (grep 게이트)
`src/**/*.{ts,tsx,css}`에 하나라도 걸리면 실패한다. 규칙은 여기가 정본이고, 스크립트는 이 목록을 따른다.
매칭 대상은 **클래스 문자열**이다 — 주석/JSDoc이 규칙을 설명하려고 패턴 이름을 인용하는 것은 위반이
아니다(이 문서와 `globals.css`·`button-variants.ts` 주석이 그렇게 쓰고 있다). 규칙을 설명하는 주석이
스스로를 위반으로 잡는 자기모순을 막기 위해, **주석에서 패턴 이름을 인용할 때는 반드시 백틱으로
감싸고** 게이트는 백틱에 싸인 매치를 제외한다:
``rg -n -- '<패턴>' src | rg -v -- '`<패턴>`'``
클래스 문자열에는 백틱이 들어갈 일이 없으므로 이 한 줄로 주석/실제 사용이 갈린다(현재 트리에서
`outline-none` 8건은 전부 백틱 주석 인용이고 제외 후 0건이다).
1. `transition-all` · `transition-colors` · 수식어 없는 `transition` — 전환 대상은 항상
   열거한다(`transition-[color,background-color,border-color]`). v4의 `transition`/`transition-colors`
   전환 목록에는 `outline-color`가 들어 있어 포커스 링을 100ms 페이드시킨다(§Focus·§Motion).
2. `text-\[\d+px\]` — 7단계 타입 스케일 밖의 크기.
3. `rounded-(2xl|3xl|4xl|\[)` — radius는 `rounded-control` / `rounded-panel` 2종.
4. `#[0-9a-fA-F]{3,8}` · `oklch(` · `rgb(` — `globals.css` 밖의 raw 색.
5. 팔레트 alpha(`bg-\w+/\d+`, `text-\w+/\d+`) — 불투명 `*-tint` 토큰을 쓴다.
6. **`outline-none`** — 조건 없이, 짝이 있든 없든 **한 번이라도 나오면 실패**다. v4에서 이 유틸은
   `outline-style: none`과 함께 내부 변수 `--tw-outline-style`을 `none`으로 박고, 같은 요소의
   `outline-<n>` 유틸은 style을 그 변수에서 읽는다. 그래서 `outline-none focus-visible:outline-2`
   처럼 레시피를 손으로 다시 적어도 링은 **그려지지 않는다**(twMerge도 둘을 다른 그룹으로 봐서
   못 지운다). 링이 필요 없는 자리는 `focus-visible:outline-0`(폭 0, style·색 무오염)을 쓰고,
   허용 목록은 §Focus의 두 가지뿐이고 **둘 다 컴포넌트 파일에 직접 적는다**(base에 allowlist를
   따로 두지 않는다 — 끄는 이유가 호출부에서 바로 보여야 한다) — ① 부모가
   `has-[input:focus-visible]:outline-*`로 대신 링을 그리는 컨트롤(`MultiFilterCombobox` 안쪽
   `Input`), ② 프로그램 포커스 전용 컨테이너 4개(`DialogContent` · `AlertDialogContent` ·
   `PopoverContent` · `AdminShell`의 `<main tabIndex={-1}>`). 어느 쪽이든 `focus-visible:outline-0`
   + 이유 주석이 한 세트다.
7. `aria-disabled:opacity-` · `aria-busy:opacity-` — 포커스를 유지하는 상태에서 root를 흐리면
   자기 포커스 링(6.66 → 2.57)과 컨트롤 경계(3.54 → 1.87)까지 함께 흐려진다(§Focus). 흐림은 라벨
   자식 래퍼에 `group-aria-disabled/…:opacity-55`로 건다. native `disabled:opacity-`는 1.4.11
   비활성 면제라 허용하지만, 새 코드는 자식 래퍼 패턴으로 통일한다.

## What every page MUST share
Rail-Workbench frame · the token vocabulary above · Pretendard/Geist Mono · the two radii · control heights
· the two hairlines (`border-border` 장식 / `border-input` 컨트롤 경계) · one focus recipe from `@layer base`
· CTA voice · status tone table(문구도 `statusLabel()` 한 곳에서) · hairline containment (1 layer)
· 흐림은 자식에만(§States) · reduced-motion rule.

## What pages MAY differ on
Only the variation knob (list / detail / map / form / dashboard / login) and which shared primitives
(`DataTable`, `DetailList`, `FilterBar`, `StatStrip`, `SelectableRow`) they compose.

## Exports
The canonical values live in `src/app/globals.css` (`:root` + `@theme inline`); no separate `tokens.css`
in this Tailwind v4 project — the `@theme` block IS the token file.
