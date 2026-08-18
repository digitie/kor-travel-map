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
- `--text-tertiary`  oklch(56% 0.012 154)     ≥ 4.5:1 on paper AND on `--surface-subtle` (was 63.5% = 3.4:1)
- `--text-disabled`  oklch(79% 0.012 154)     non-text use only (never as the only cue)
- `--brand`          oklch(51.4% 0.081 169)   accent (unchanged) — links, primary CTA fill, active nav mark
- `--brand-hover`    oklch(46% 0.085 169)
- `--brand-tint`     oklch(95.2% 0.013 172)   selected row / active nav wash (opaque)
- `--brand-foreground` oklch(99% 0.002 140)
- `--success` oklch(46.9% 0.087 149) · `--success-tint` oklch(95% 0.03 150)
- `--warning` oklch(50.9% 0.103 71)  · `--warning-tint` oklch(96% 0.035 80)
- `--info`    oklch(50% 0.16 258)     · `--info-tint`    oklch(95.5% 0.025 255)   (was blue-500 = 3.7:1)
- `--destructive` oklch(51.4% 0.167 27) · `--destructive-tint` oklch(96% 0.03 25)
- `--focus`   oklch(45% 0.09 169)     opaque focus outline (5.4:1 on paper; used with offset 2px)
- `--overlay` oklch(30% 0.006 157 / 0.45)  the ONLY allowed alpha colour (dialog scrim)
- `--compare-a` oklch(51.4% 0.081 169) · `--compare-b` oklch(50% 0.16 258)  dedup/compare marker pair
- shadcn aliases (`--background/--foreground/--primary/--ring/--card/--popover/--muted/--accent/--input`)
  stay defined and mapped in `@theme`, but component code speaks the project vocabulary above.
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
- Control heights: `--control-h` 36px · `--control-h-sm` 30px. All buttons/inputs/selects use one of them.
- Rail: `--rail` 22rem (right inspector) · sidebar 16rem.
- Depth: rest = hairline (`border-border`), no shadow. Shadow only for overlays (`--shadow-elevated` for
  popover/menu, `--shadow-modal` for dialog). `--shadow-card*` remain defined but unused by default.

## Motion
- Easings: `--ease-out` cubic-bezier(0.16, 1, 0.3, 1) · `--ease-in` cubic-bezier(0.7, 0, 0.84, 0).
- Durations: `--dur-fast` 100ms (hover/colour) · `--dur-base` 150ms (overlay enter, opacity+scale .98).
- Animate `opacity`/`transform` only; `transition-[color,background-color,border-color,box-shadow]` for
  state colour changes; **`transition-all` is banned**. Focus ring appears instantly (outside transitions).
- `prefers-reduced-motion: reduce` → all spatial motion collapses to ≤ 150ms opacity crossfade (global rule).
- Live-updating regions (ops streams/logs) never re-order or flash on update.

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
- Secondary: outline (`border-border`, ink text); ghost only inside toolbars/tables.
- Destructive: `--destructive` fill only inside confirm dialogs; in-page it is an outline with destructive text.
- Links in prose: `--brand` underline on hover; links styled as buttons take the button recipe (no underline).

## Status colour semantics (single tone table — `src/lib/status-label.ts`)
`success` = 활성/완료/ready · `warning` = 검토 필요/대기/quarantine · `destructive` = 실패/blocked/dead-letter
· `info` = draft/candidate/valid(informational) · `neutral` = archived/disabled/unknown. Every badge, dot,
option and column reads this table; enum values are never rendered raw.

## Copy
- Buttons/nav are verbs or task nouns already in use (중복 검토, 보강 검토, 정합성 점검). No `확인` on a
  confirm — name the action. Errors: what · why · what to do (`AppErrorPanel`). Empty states: left-aligned,
  one sentence + one action, no icon-above-title tile. Null glyph `—` (not `-`), separators `·`.
- Never invent metrics: loading shows `—`, never a false 0.

## What every page MUST share
Rail-Workbench frame · the token vocabulary above · Pretendard/Geist Mono · the two radii · control heights
· CTA voice · status tone table · hairline containment (1 layer) · reduced-motion rule.

## What pages MAY differ on
Only the variation knob (list / detail / map / form / dashboard / login) and which shared primitives
(`DataTable`, `DetailList`, `FilterBar`, `StatStrip`, `SelectableRow`) they compose.

## Exports
The canonical values live in `src/app/globals.css` (`:root` + `@theme inline`); no separate `tokens.css`
in this Tailwind v4 project — the `@theme` block IS the token file.
