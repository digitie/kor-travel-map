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
- `--text-secondary` oklch(48% 0.012 159)     ink-2 (labels, captions) ≥ 7:1
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
  대비 요건 없음(정보를 나르지 않는다).
- `--control-line` oklch(61% 0.012 145)  **조작 가능한 요소의 경계 전용** — input · textarea ·
  native-select · checkbox · combobox 껍데기 · outline 버튼. `--input`(shadcn 이름)이 이 값을
  가리키므로 컴포넌트는 계속 `border-input`을 쓴다. WCAG 1.4.11(non-text contrast) 대상이라
  인접 배경 대비 **3:1 이상**: card 3.69:1 · `--surface-page` 3.54:1 · `--surface-subtle` 3.43:1
  · `--surface-muted` 3.03:1. (직전 값 oklch(89% 0.01 145)는 card 1.36:1 / page 1.30:1 / subtle
  1.26:1로 전부 미달 — 컨트롤이 배경에 녹아 보였다.)
  Dark: oklch(58% 0.012 145) → card 3.96:1 · page 4.33:1 · subtle 3.85:1 · muted 3.07:1
  (직전 oklch(36% 0.012 145)는 card 1.56:1). 값을 바꿀 때는 이 네 표면 전부에서 3:1을 다시 계산한다.
- `--focus`   oklch(45% 0.09 169)     opaque focus outline (5.4:1 on paper; used with offset 2px)
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
  - `Checkbox` `size-4`(표준 체크박스 크기, 히트 타깃은 `after:-inset-3.5`)
- Rail: `--rail` 22rem (right inspector) · sidebar 16rem.
- Depth: rest = hairline (`border-border`), no shadow. Shadow only for overlays (`--shadow-elevated` for
  popover/menu, `--shadow-modal` for dialog). `--shadow-card*` remain defined but unused by default.

## Motion
- Easings: `--ease-out` cubic-bezier(0.16, 1, 0.3, 1) · `--ease-in` cubic-bezier(0.7, 0, 0.84, 0).
- Durations: `--dur-fast` 100ms (hover/colour) · `--dur-base` 150ms (overlay enter, opacity+scale .98).
- Animate `opacity`/`transform` only; `transition-[color,background-color,border-color,box-shadow]` for
  state colour changes; **`transition-all` is banned**. Focus ring appears instantly (outside transitions).
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
  선언하지 않아도 링을 받는다는 뜻이다. 전환 대상이 아니므로 즉시 나타난다.
- **무조건부 `outline-none` 금지.** Tailwind utility는 `@layer base`를 이기므로 `outline-none`
  하나만 붙이면 그 요소는 포커스 링을 영구히 잃는다. 정말 꺼야 하는 자리(부모 래퍼가
  `has-[input:focus-visible]:outline-*`로 대신 링을 그리는 경우)에서만 끄고, 그때는 왜 껐는지
  주석을 남긴다.
- 링을 요소 안쪽에 그려야 하는 경우(표 헤더처럼 이웃 셀에 잘리는 자리)만
  `focus-visible:-outline-offset-2`를 쓴다. 색은 항상 `outline-focus`.

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
- Primary: solid `--brand` fill, `--radius-control`, 500, verb label (`저장`, `적용`, `가져오기`); one per band.
- Secondary: outline (`border-input` — 조작 가능한 경계라 장식용 `border-border`가 아니다; ink text);
  ghost only inside toolbars/tables.
- Destructive: `--destructive` fill only inside confirm dialogs; in-page it is an outline with destructive text.
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

## Copy
- Buttons/nav are verbs or task nouns already in use (중복 검토, 보강 검토, 정합성 점검). No `확인` on a
  confirm — name the action. Errors: what · why · what to do (`AppErrorPanel`). Empty states: left-aligned,
  one sentence + one action, no icon-above-title tile. Null glyph `—` (not `-`), separators `·`.
- Never invent metrics: loading shows `—`, never a false 0.

## 금지 패턴 (grep 게이트)
`src/**/*.{ts,tsx,css}`에 하나라도 걸리면 실패한다. 규칙은 여기가 정본이고, 스크립트는 이 목록을 따른다.
1. `transition-all` — 전환 대상은 항상 열거한다(`transition-[color,background-color,border-color]`).
2. `text-\[\d+px\]` — 7단계 타입 스케일 밖의 크기.
3. `rounded-(2xl|3xl|4xl|\[)` — radius는 `rounded-control` / `rounded-panel` 2종.
4. `#[0-9a-fA-F]{3,8}` · `oklch(` · `rgb(` — `globals.css` 밖의 raw 색.
5. 팔레트 alpha(`bg-\w+/\d+`, `text-\w+/\d+`) — 불투명 `*-tint` 토큰을 쓴다.
6. **`outline-none`** — 한 요소의 className(= 하나의 `cn(...)` 호출 전체, 인자가 여러 문자열로
   쪼개져 있어도 하나로 본다)에 `outline-none`과 `focus-visible:outline-`이 **함께** 있으면 걸린다.
   둘의 동시 사용은 `@layer base`의 포커스 레시피를 지운 뒤 같은 레시피를 손으로 다시 적는 중복이라,
   링 두께·offset·색이 파일마다 갈라지는 drift의 출처다(§Focus). 링은 base가 발행하니 그냥 두
   클래스를 **모두 지우면** 된다. `outline-none`만 있고 짝이 없는 경우는 더 나쁘다 — 그 요소는
   포커스 링을 영구히 잃으므로 무조건 지운다. 유일한 예외는 부모 래퍼가
   `has-[input:focus-visible]:outline-*`로 대신 링을 그리는 자리이고, 그때는 이유를 주석으로 남긴다.

## What every page MUST share
Rail-Workbench frame · the token vocabulary above · Pretendard/Geist Mono · the two radii · control heights
· the two hairlines (`border-border` 장식 / `border-input` 컨트롤 경계) · one focus recipe from `@layer base`
· CTA voice · status tone table · hairline containment (1 layer) · reduced-motion rule.

## What pages MAY differ on
Only the variation knob (list / detail / map / form / dashboard / login) and which shared primitives
(`DataTable`, `DetailList`, `FilterBar`, `StatStrip`, `SelectableRow`) they compose.

## Exports
The canonical values live in `src/app/globals.css` (`:root` + `@theme inline`); no separate `tokens.css`
in this Tailwind v4 project — the `@theme` block IS the token file.
