# hallmark audit — kor-travel-map admin frontend (2026-08-18)

> 범위: `frontend/` admin/ops 콘솔 전체 (shell + 29 ui primitives + 27 routes). 채점 기준: APP 페이지(dense data UI). 4개 감사 그룹(shell-tokens · pages-features · pages-admin · pages-ops)의 findings를 tell 단위로 병합·중복 제거한 최종본(검증자 refute 0건, pages-ops severity 보정 critical→major 2건 · major→minor 3건 반영). 후속 `hallmark redesign`(multi-page flow → `design.md` 선행)의 입력 문서.

## 0. Pre-flight (확정 사실 — 재도출 금지, 원문 인용)

> Next.js 16 app router · React 19 · Tailwind v4 (`@import "tailwindcss"` + `@theme inline` in src/app/globals.css, 227 lines)
> · shadcn-style tokens (--background/--primary/--brand/--surface-*/--text-* mapped via @theme) · Geist via next/font (src/app/layout.tsx L10/L20, --font-sans)
> · tw-animate-css (motion-lite; no framer-motion) · 29 shadcn-ish ui components in src/components/ui · shell chrome in src/components/admin-shell.tsx
> · 27 page.tsx routes · no .hallmark/, no design.md.
> This is an internal OPS/ADMIN console (Korean UI copy) — grade it as APP pages (dense data UI), not as a marketing landing: the "centered hero → 3 cards → CTA" structural check mostly does not apply,
> but table/filter/panel/toast/empty-state/skeleton/badge/status-colour disciplines, typography scale, spacing scale, token discipline (no inline hex/oklch improvisation), colour-as-meaning, contrast, focus rings, 8-state buttons, motion restraint, copy voice (verbs, error structure), and generic-AI-shell tells (identical card grids, gradient blobs, glassmorphism, emoji bullets, "Welcome back" heroes, purple gradients, generic empty states) DO apply.

## 1. 구조 지문 — 하나의 설계된 시스템인가, generic AI shell인가

**판정: "토큰층은 시스템, 조합·음성층은 템플릿."** 토큰 규율(컴포넌트 안 inline hex 0건, lucide 단일 아이콘, gradient/blob/glass/emoji 0건, 녹색 브랜드 틴트 중립색)과 프레임 일관성(모든 페이지가 `AdminShell` h1+breadcrumb+actions 안, toolbar→list→inspector 리듬)은 실제로 하나의 시스템처럼 읽힌다. 그러나 사용자가 처음 5초에 보는 것은 shadcn admin 템플릿의 지문이다 — 흰 사이드바 + `bg-brand-tint` 둥근 사각형 안 `MapIcon` 워드마크 + 11px uppercase 그룹 라벨 + ghost 버튼 pill nav + 하단 고정 로그아웃 + 콘텐츠 첫 요소가 떠 있는 `rounded-2xl` 그림자 헤더 카드(`admin-shell.tsx:193-359`); 홈의 icon-tile KPI 4-up 그리드 + `text-[36px] font-bold` 숫자(`home-client.tsx:48-93,318-385`); 모든 컨테이너에 border+shadow+hover-elevation이 동시에 걸린 18px 라운드 카드(`card.tsx:15`); dashed-border 가운데 정렬 아이콘-위-제목 EmptyState(`empty-state.tsx:18-30`); 기본 문구 `데이터가 없습니다.`/`알 수 없는 오류`/`확인`; 로그인의 icon-in-tinted-square 카드(`login-form.tsx:62-72`). 결정적으로 **한글 전용 서체가 없다** — Geist는 `subsets: ["latin"]`만 로드되고 Pretendard/Noto Sans KR은 이름만 있어 이 한국어 콘솔의 대부분 글리프가 Malgun Gothic으로 렌더된다(`layout.tsx:20`, `globals.css:69-70`). 즉 색·그림자·아이콘은 정돈됐지만 서체·라운드·카드 chrome·홈 구성·빈 상태·버튼 라벨이 "AI가 만든 관리자 대시보드"로 읽히며, 페이지층에서는 같은 일(master-detail)이 4가지 macro와 3가지 컨테이너 idiom(`rounded-lg border bg-background` 회색 flat box vs `SectionCard` vs `Card`)으로 갈라져 시스템이 아니라 freestyle로 흩어진다. ops 페이지(pipeline/datasets/logs/consistency/cache-target-streams)도 같은 지문 — KPI 표기 4종, row당 badge 4–7개, `font-mono` 83건, 상단 Alert 벽 — 이며, 토큰 규율은 지키되 조합층은 페이지마다 다시 발명됐다.

## 2. Findings

표기: **Tell** (anti-pattern / gate) · **Where** (path:lines) · **Severity** · **Fix** · `evidence`. 병합 findings는 출처 그룹(shell-tokens / pages-features / pages-admin / pages-ops)을 표기하고, 검증자 severity 보정이 있으면 tell 끝에 괄호로 남긴다.

### 2.1 Critical

**C1 · Focus ring < 3:1 / 포커스 지시자 제거 후 대체 부재** — slop-test gate 26+40; interaction-and-states § Focus rings; gate 15(포커스가 fade-in)
- Where: `src/app/globals.css:146`, `src/components/ui/button-variants.ts:4`, `src/components/ui/input.tsx:12`, `src/components/ui/textarea.tsx:10`, `src/components/ui/native-select.tsx:29`, `src/components/ui/badge.tsx:8`, `src/components/ui/checkbox.tsx:13`, `src/components/ui/tabs.tsx:61` (대조: `src/components/ui/data-table.tsx:314`, `src/components/help-tip.tsx:34`, `src/components/copy-button.tsx:36`)
- Severity: **critical** · scope a11y · 출처 shell-tokens
- Evidence: `* { @apply border-border outline-ring/50; } … outline-none … focus-visible:border-brand focus-visible:ring-3 focus-visible:ring-brand/20 … focus-visible:ring-3 focus-visible:ring-ring/50`
- Fix: 포커스 토큰 1개·레시피 1개 — `focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[--ring]`(불투명 brand, 5.4:1); `/20`·`/50` alpha halo 제거, base layer `outline-ring/50` 제거, ring은 `transition-colors` 밖(즉시 표시), primary(`bg-brand`) 버튼은 offset ring으로 동색 border 회피.

**C2 · 토큰에 구워진 대비 실패 — `--info` = raw Tailwind blue-500(흰 배경 3.7:1, `/10` 틴트 위 3.3:1), `--text-tertiary` 3.4:1, 둘 다 12–14px 텍스트/placeholder/status badge로 사용** — gate 40/41; color.md placeholder ≥ 4.5:1
- Where: `src/app/globals.css:99,102-106`, `src/components/ui/badge.tsx:24`, `src/components/ui/input.tsx:12`, `src/components/ui/textarea.tsx:10`, `src/components/ui/native-select.tsx:29`; info badge 소비처 `src/app/admin/features/curated/curation-collections-client.tsx:102-118,748-750,779-781,1091-1093,1409-1411`
- Severity: **critical** · scope token · 출처 shell-tokens + pages-features 병합
- Evidence: `--text-tertiary: #858d87; /* WCAG AA(4.5:1) … */ --success: #33683f; --warning: #8a5a12; --info: #3b82f6;` · `if (status === "draft" || status === "candidate" || status === "valid") { return "info" as const; }` → `text-info` on `bg-info/10`, 12px bold uppercase ≈ 3.3:1
- Fix: `--info`를 `--success/--warning`처럼 어둡게(≈`#2b5fb8`~`#1f56b3`, 흰 배경·`/10` 틴트 모두 ≥ 4.5:1); `--text-tertiary`를 ≥ 4.5:1(≈`#6b746e`)로 올리거나 비텍스트(아이콘/rule) 전용으로 제한하고 placeholder/caption은 `--text-secondary` 사용.

**C3 · Card-in-card — 최대 3중 containment** — anti-patterns § Card-in-card; gate 4
- Where: `src/app/admin/features/curated/curation-quarantine-panel.tsx:792→367,727→393,435,652,668`; `src/app/admin/features/curated/curation-collections-client.tsx:1189→796,861`; `src/app/home-client.tsx:418→427,450,482→490`; `src/app/features/features-client.tsx:900→714,762`; `src/app/curated-features/curated-feature-map-client.tsx:503→605,636,217→129`; `src/app/admin/curations/candidates/curation-candidates-client.tsx:821-839`; `src/app/admin/files/files-client.tsx:352-403`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:341,552`; `src/app/ops/logs/logs-client.tsx:367-421,426-471`; `src/app/ops/consistency/consistency-client.tsx:199-219,222-252`; `src/app/ops/datasets/datasets-client.tsx:2743,1749,1760-1897,874,1051,1126-1188`; `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:536-589,449-455`
- Severity: **critical** · scope structure · 출처 pages-features + pages-admin + pages-ops 병합
- Evidence: `<SectionCard title="격리 collection 재분류"> … <SectionCard title="격리 collection"> … <button className="w-full rounded-xl border p-3 …">` · `<CardContent> … <li className="rounded-lg border p-4">` · `<div className="flex flex-col gap-2 rounded-md border border-destructive/40 p-3">` inside `<SectionCard>` · ops: `<section className="rounded-lg border bg-background"> … <DataTable containerClassName="overflow-auto"/>`(ui/table.tsx L11이 이미 `rounded-xl border` — radius lg/xl 불일치 포함), datasets drawer는 `rounded-xl bg-surface-subtle` 패널 스택 + 내부 `bg-card` 블록 3중
- Fix: region당 containment 1층 — 바깥 quarantine SectionCard 제거, summary dl/form은 hairline rule 아래 flat, 선택 타일은 borderless row(bg 변화만), map/table Card를 감싸는 `rounded-lg border bg-muted/30` 프레임 제거, transitions는 `divide-y` 리스트, purge 블록은 destructive 버튼 하나 있는 plain footer row; ops는 Table 자체 border를 컨테이너로(래퍼 section 삭제), datasets drawer 패널 스택 → plain sub-heading + hairline rule.

### 2.2 Major

**M1 · `transition-all`** — anti-patterns § Microinteraction tells #1; slop-test gate 10(금지 클래스)
- Where: `src/components/ui/tabs.tsx:61` · Severity: major · scope motion · 출처 shell-tokens
- Evidence: `… text-foreground/60 transition-all`
- Fix: `transition-[color,background-color,box-shadow] duration-150`; after: underline은 `transition-opacity`만.

**M2 · 실제 UI 언어에 시스템 기본 서체 — Geist latin-only, Pretendard/Noto Sans KR은 이름만; 제목·본문 단일 family; 토큰화 안 된 system mono(`--font-mono` 없음)** — typography.md § Banned defaults; gate 1
- Where: `src/app/layout.tsx:20`, `src/app/globals.css:69-70,157-159`, `src/components/admin-shell.tsx:313`, `src/components/detail-list.tsx:67`, `src/components/json-viewer.tsx:45`; `font-mono` 소비처 `src/app/home-client.tsx:86,201`, `src/app/features/features-client.tsx:127,180,401`, `src/app/admin/features/admin-features-client.tsx:165,191,409,432,492`, `src/app/admin/features/curated/curation-collections-client.tsx:1016,1027,1065,1407`, `src/app/curated-features/curated-feature-map-client.tsx:364`, `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:143`, `src/app/admin/curated-features/curated-features-client.tsx:143,206,210`; ops(`font-mono` src/app/ops 83건, count·label까지 mono): `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:210-252`, `src/app/ops/pipeline/schedule-panel.tsx:92-128`, `src/app/ops/datasets/datasets-client.tsx:1541-1549`
- Severity: major · scope token · 출처 shell-tokens + pages-features + pages-ops 병합
- Evidence: `const geist = Geist({ subsets: ["latin"], variable: "--font-sans" }); … font-family: var(--font-sans), Pretendard, "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;` · `<span className="font-mono">…</span>`(ui-monospace/Consolas fallback) · `<span className="font-mono text-xs">{formatCount(pendingCount)} pending / {formatCount(leasedCount)} lease / {formatCount(retryCount)} retry</span>`
- Fix: Pretendard Variable을 `next/font/local`(self-host, `font-display: swap`, size-adjust fallback)로 한글/본문 face, Geist는 Latin/숫자만 — 또는 Geist 제거·Pretendard 단독; Geist Mono를 `--font-mono`로 로드해 `@theme` 매핑(ID/path/JSON); mono는 식별자/key/cron/JSON에만, count는 본문 face + `tabular-nums`(M24).

**M3 · 1px 단위 type scale(11/12/13/14/16/18/20/24/36px) — 일부는 `text-[Npx]`, 일부는 `text-xs/sm/base`; `font-bold`가 button·badge·th·nav·card title·h1에 동일 적용되어 위계 평탄화** — typography.md § Scale(≤ 5 sizes); gate 24
- Where: `src/components/ui/button-variants.ts:4,23,24`, `src/components/ui/badge.tsx:8`, `src/components/ui/card.tsx:15,48,60`, `src/components/ui/table.tsx:15,73`, `src/components/admin-shell.tsx:228,265,313,342,346`, `src/components/status-badge.tsx:67`, `src/components/ui/alert.tsx:7,51,67` vs `src/components/ui/field.tsx:31,123,136,217`, `src/components/ui/dialog.tsx:73,86`, `src/components/ui/tabs.tsx:61,76`, `src/components/empty-state.tsx:25,27`, `src/components/filter-bar.tsx:35`, `src/components/detail-list.tsx:60,66`, `src/components/ui/data-table.tsx:105-112`; 페이지: `src/app/home-client.tsx:66,86-87,105,342,368,431,454,490,497,503`, `src/components/login-form.tsx:69-70,75,90`; `src/app/admin/settings/settings-client.tsx:215,265`(`text-[16px]` h2); ops(`text-[13px]` ×21 vs `text-xs` ×83 vs `text-sm` ×29 혼재): `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:340-369,424,547`, `src/app/ops/datasets/datasets-client.tsx:1128,1452,1695,1774-1824,1980-1985`, `src/app/ops/pipeline/pipeline-client.tsx:127`
- Severity: major · scope token · 출처 shell-tokens + pages-features + pages-admin + pages-ops 병합
- Evidence: `text-[14px] font-bold … sm: "h-10 … text-[13px]" … text-[11px] … CardTitle "text-[18px] … font-bold"` vs `AlertDialogTitle "text-base font-semibold"`, `FieldTitle "text-sm font-medium"`, 12px th 안 13px sortable button · `<span className="pb-0.5 text-[18px] leading-none font-bold">` · `<h2 className="text-[16px] font-semibold">공개 API 키</h2>` · `<CardContent className="text-[13px] text-text-secondary"> … <CardTitle className="break-all font-mono text-[14px]">`
- Fix: `@theme`에 `--text-2xs…--text-2xl`을 한 비율(예 12/13.5/15/17/20/24/30)로 정의, 모든 `text-[Npx]` 삭제, 700은 h1/h2 전용 — button/badge/th/nav는 500/600.

**M4 · Alpha transparency가 팔레트 + raw `black` — 컴포넌트마다 `/5 /10 /20 /30 /40 /45 /50 /60 /70 /80 /90` 즉흥 틴트** — color.md § Bans 'alpha as colour definition'; gate 48; gate 7 pure black
- Where: `src/components/ui/button-variants.ts:9,13,17`, `src/components/ui/badge.tsx:16,22-24`, `src/components/ui/card.tsx:15`, `src/components/ui/tabs.tsx:61,63`, `src/components/ui/field.tsx:109`, `src/components/ui/alert.tsx:13`, `src/components/json-viewer.tsx:46-48`, `src/components/ui/dialog.tsx:34`, `src/components/ui/alert-dialog.tsx:26`, `src/components/admin-shell.tsx:307`
- Severity: major · scope token · 출처 shell-tokens
- Evidence: `hover:bg-brand/90 … hover:bg-brand-tint/80 … bg-destructive/10 hover:bg-destructive/20 … ring-1 ring-border/70 … text-foreground/60 … bg-muted/40 … bg-primary/5 … bg-black/45`
- Fix: 불투명 토큰(`--brand-hover`, `--success-tint`, `--warning-tint`, `--info-tint`, `--destructive-tint`, `--overlay`)을 `:root`/`.dark`에 추가해 참조; alpha는 modal backdrop·shadow에만, backdrop은 `black`이 아닌 `--text-primary`에서 파생.

**M5 · 한 개념에 두 토큰 어휘 — brand/primary/ring, text-text-secondary/muted-foreground, bg-card/bg-background/bg-popover(elevated surface), font-bold/semibold/medium(title) — shadcn alias와 프로젝트 이름이 동시에 live** — anti-patterns § Mid-render token improvisation
- Where: `src/components/ui/checkbox.tsx:13`, `src/components/ui/tabs.tsx:61-63`, `src/components/ui/field.tsx:109,138`, `src/components/detail-list.tsx:51`, `src/components/ui/dialog.tsx:43,86`, `src/components/ui/alert-dialog.tsx:35,55,68`, `src/components/ui/breadcrumb.tsx:15,37,48`, `src/components/pagination-bar.tsx:41,45`, `src/components/copy-button.tsx:36`, `src/components/help-tip.tsx:34`, `src/components/ui/data-table.tsx:429,464`
- Severity: major · scope token · 출처 shell-tokens
- Evidence: `data-checked:bg-primary … focus-visible:ring-ring/50` | `"text-primary underline-offset-2"` | `DialogContent "bg-background"` vs `PopoverContent "bg-popover"` vs `Card "bg-card"` | `DialogTitle "text-lg font-semibold"` vs `CardTitle "text-[18px] … font-bold"`
- Fix: 프로젝트 이름(brand / surface-* / text-*)만 public 어휘로, shadcn alias는 `@theme`에서 그쪽으로 매핑하고 컴포넌트에서 `primary|ring|muted-foreground|foreground|background` lint; dialog도 다른 elevated surface처럼 `bg-card`.

**M6 · 규칙 없는 radius — 4/8/10/14/18px 공존(checkbox 4, input·sm button 8, default button·dialog 10, table·logo tile 14, card·alert·header 18); 18px 라운드 그림자 카드 = friendly-SaaS 대시보드 템플릿; 페이지에서도 `rounded-md/xl` 내부 박스 혼재** — layout-and-space § Depth
- Where: `src/app/globals.css:65-68,84-86`, `src/components/ui/card.tsx:15`, `src/components/ui/alert.tsx:7`, `src/components/admin-shell.tsx:223,307`, `src/components/ui/table.tsx:11`, `src/components/ui/button-variants.ts:4,23,24`, `src/components/ui/dialog.tsx:43`, `src/components/ui/checkbox.tsx:13`, `src/components/copy-button.tsx:36`; 페이지 radius drift는 M7 위치 참조
- Severity: major · scope token · 출처 shell-tokens (+ pages-features radius 부분)
- Evidence: `--radius: 0.625rem; --radius-2xl: calc(var(--radius) * 1.8) … Card "rounded-2xl bg-card p-6 … shadow-[var(--shadow-card)] ring-1 ring-border/70" … Table "rounded-xl border" … default "rounded-lg" vs sm "rounded-md"`
- Fix: radius 2개만 — `--radius-control: 6px`(button/input/badge/tab), `--radius-panel: 10px`(card/table/dialog); `--radius`를 6px로, `1.8/2.2/2.6` 배수 삭제.

**M7 · Surface idiom drift — 회색 flat box(`rounded-lg border bg-background p-4`, SectionCard docstring이 이미 deprecate) vs `SectionCard` vs `Card` vs bespoke `border-surface-muted bg-card` section이 같은 그룹 안에 3–4종** — mid-render token improvisation analog; gate 48/24
- Where: `src/app/admin/features/admin-features-client.tsx:144,152,661,898`; `src/app/admin/features/feature-form-sections.tsx:98,203,336,471,422,562`; `src/app/admin/features/new/feature-create-client.tsx:870,961,1080,930,1003`; `src/app/admin/curated-features/curated-features-client.tsx:78,84,177`; `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:103`; `src/app/admin/curated-features/curated-lifecycle.tsx:76`; `src/components/login-form.tsx:63`; `src/app/admin/issues/admin-issues-client.tsx:196,258,277,811,936`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:191,423,437,624,1009`; `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:386,467,513`; `src/app/admin/dedup-reviews/dedup-review-client.tsx:182,492,904`; `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:320,375,617,792`; `src/app/admin/settings/settings-client.tsx:212,262`
- Severity: major · scope component · 출처 pages-features + pages-admin 병합
- Evidence: `<section className="rounded-lg border bg-background p-4">` · `<section className="space-y-4 rounded-lg border border-surface-muted bg-card p-5">` vs `SectionCard/Card "rounded-2xl bg-card ring-1 ring-border/70 shadow"`
- Fix: 모든 bespoke bordered box를 `SectionCard`(title/description/actions)로 수렴 — 패널 chrome·radius·padding·header 리듬 1종; 컨테이너 radius는 M6의 2값으로 고정.

**M8 · Card chrome — 비인터랙티브 컨테이너에 border AND shadow AND hover-elevation 동시; 카드 레시피가 3곳에 수기 복사** — layout-and-space § Depth 'use one'; anti-patterns § Universal hover effects; § Every section padded the same
- Where: `src/components/ui/card.tsx:15`, `src/components/admin-shell.tsx:202,307`, `src/components/app-error-panel.tsx:71`, `src/components/ui/alert.tsx:7`, `src/components/pagination-bar.tsx:41`, `src/components/ui/popover.tsx:35`, `src/components/ui/tooltip.tsx:36`, `src/app/globals.css:107-110`
- Severity: major · scope component · 출처 shell-tokens
- Evidence: `rounded-2xl bg-card p-6 … shadow-[var(--shadow-card)] ring-1 ring-border/70 transition-shadow … hover:shadow-[var(--shadow-card-hover)]`(admin-shell.tsx:307, app-error-panel.tsx:71에 재타이핑); `PagerShell "rounded-lg border bg-background"` inside a Card; popover·tooltip 모두 `--shadow-modal`, `--shadow-elevated` 미사용
- Fix: 카드는 hairline border만, rest shadow 없음; `--shadow-card-hover`는 실제 클릭 가능한 요소(`data-interactive`)에만; popover→`--shadow-elevated`, dialog→`--shadow-modal`; header·error panel은 `<Card>` 사용.

**M9 · The AI admin shell — 흰 사이드바 + tinted-rounded-square 아이콘 워드마크 + uppercase 11px 그룹 라벨 + lucide ghost-button nav + tinted pill active + 하단 고정 logout + 떠 있는 page-header 카드** — anti-patterns § The AI nav / genre-blind chrome; gate 42(app shell analogue)
- Where: `src/components/admin-shell.tsx:193-359` (aside 202-304, header 306-355)
- Severity: major · scope shell · 출처 shell-tokens
- Evidence: `<aside className="… bg-card shadow-[var(--shadow-card)] lg:border-r"> … <span className="flex size-10 … rounded-xl bg-brand-tint text-brand"><MapIcon className="size-4"/></span> … <header className="px-6 pt-6"><div className="… rounded-2xl bg-card p-6 shadow-… ring-1 ring-border/70 …">`
- Fix: ops 콘솔로 읽히게 — typographic 워드마크(아이콘 타일 제거), rail에 상시 status strip(환경, API/Dagster health dot, 마지막 pipeline run), nav 그룹은 pill 대신 small-caps 텍스트 + 1px rule, 떠 있는 카드 대신 flush page-header band(breadcrumb + h1 + actions 한 baseline, 아래 hairline).

**M10 · 전역 `a { hover:underline }`이 Link-as-button으로 누출 — 사이드바 nav 전부와 `<Link className={buttonVariants()}>` 전부 hover 시 밑줄** — template-leak tell; reset 없는 hover-only 스타일
- Where: `src/app/globals.css:162-164`, `src/components/admin-shell.tsx:276-296`, `src/components/ui/breadcrumb.tsx:33-40` (+ buttonVariants on Link 사용 페이지 13개)
- Severity: major · scope shell · 출처 shell-tokens
- Evidence: `a { @apply text-brand underline-offset-4 hover:underline; } … <Link className={cn(buttonVariants({ variant: active ? "secondary" : "ghost", size: "sm" }), "justify-start whitespace-nowrap")}`
- Fix: anchor 규칙을 prose로 스코프(`.prose a` 또는 `a:not([class])`), buttonVariants base에 `no-underline hover:no-underline`.

**M11 · Shell semantics/a11y — `<main>`이 nav·header를 감쌈, 19항목 nav 건너뛰는 skip link 없음, active nav는 색만(`aria-current` 없음), 모바일 nav는 그룹 제목 숨긴 무라벨 가로 strip** — interaction-and-states § Bans: colour-only state; hover/keyboard parity
- Where: `src/components/admin-shell.tsx:193,248-301,276-296,250-271`
- Severity: major · scope a11y · 출처 shell-tokens
- Evidence: `<main className="min-h-screen …"> <div className="grid …"> <aside …> … <nav className="flex max-w-full gap-1 overflow-x-auto lg:… lg:flex-col"> … <Link aria-label={sidebarCollapsed ? item.label : undefined} className={cn(buttonVariants({ variant: active ? "secondary" : "ghost" …`
- Fix: `<main>`은 `{children}`만(aside/header 밖으로), active Link에 `aria-current="page"` + 비색상 마커(left rule / weight), `본문으로 건너뛰기` skip link, `<lg`에서는 scroll strip 대신 그룹 제목 있는 sheet.

**M12 · Input 높이 ≠ Button 높이, 한 시스템에 컨트롤 높이 4종+ — Input 40 / Button default 44 / sm 40 / xs 32 / select sm 36 / tabs 32 / sortable th button 32; 폼 row에서 h-10 input 옆 h-11 버튼** — slop-test gate 39 'height mismatch'; interaction-and-states § Heights and rhythm
- Where: `src/components/ui/input.tsx:12`, `src/components/ui/button-variants.ts:22-31`, `src/components/ui/native-select.tsx:29`, `src/components/ui/tabs.tsx:27`, `src/components/ui/data-table.tsx:108`; `src/components/login-form.tsx:78-114`, `src/app/admin/features/new/feature-create-client.tsx:891-916`, `src/app/admin/features/curated/curation-collections-client.tsx:632-683`
- Severity: major · scope component · 출처 shell-tokens + pages-features 병합
- Evidence: `Input "h-10 …"` vs `default: "h-11 gap-2 px-4 …"` vs `data-[size=sm]:h-9` vs `group-data-horizontal/tabs:h-8` vs `<Button variant="ghost" size="sm" className="-ml-2 h-8 px-2 …">` · `<Input … />`(h-10) … `<Button className="w-full" …>로그인</Button>`(h-11)
- Fix: 높이 2개 — `--control-h: 40px`(input/select/textarea-row/default button/tab), `--control-h-sm: 32px`(dense table/filter chrome); Button default h-10, Input `size="sm"` h-8 제공(ad-hoc override 금지).

**M13 · Field helper/error slot — hint와 error 동시 렌더, 높이 미예약 → validation이 폼을 밀어냄; 페이지에서는 error Alert가 CTA 뒤에 렌더** — gate 39 'helper-text slot collapses'; interaction-and-states § Labels, helper, error
- Where: `src/components/ui/form-field-input.tsx:69-70`, `src/components/ui/form-select.tsx:70-71`, `src/components/ui/form-textarea.tsx:69-70`, `src/components/ui/field.tsx:131-144,176-223`; `src/components/login-form.tsx:78-114`; `src/app/ops/pipeline/execution-timeline.tsx:592-599,629-636`(prerequisite hint mount/unmount → 층 이동)
- Severity: major · scope component · 출처 shell-tokens + pages-features + pages-ops 병합
- Evidence: `{hint ? <FieldDescription id={hintId}>{hint}</FieldDescription> : null}` `{error ? <FieldError id={errorId}>{error}</FieldError> : null}` · `{error ? <Alert variant="destructive"> … : null}` rendered after the button · `{!providerDatasetIdFilter ? (<p className="text-xs text-text-tertiary" id="timeline-scope-prerequisite">provider dataset ID를 먼저 입력하세요.</p>) : null}`
- Fix: `min-h-[1lh]` 메시지 슬롯 1개: error가 있으면 hint 대체(`aria-describedby`는 표시 중인 것으로); 페이지 error는 CTA 위 min-h 예약 슬롯에; helper 컨테이너는 항상 렌더하고 텍스트만 교체.

**M14 · `prefers-reduced-motion` 전무 — skeleton pulse, spinner, dialog/popover scale, 사이드바 smooth `scrollIntoView`, tw-animate 모두 무조건 실행** — slop-test gate 27; microinteractions § Accessibility ground truth
- Where: `src/components/ui/skeleton.tsx:7`, `src/components/ui/sonner.tsx:28`, `src/components/ui/dialog.tsx:44`, `src/components/ui/alert-dialog.tsx:36`, `src/components/ui/popover.tsx:36`, `src/components/ui/tooltip.tsx:37`, `src/components/admin-shell.tsx:173-178`, `src/app/globals.css:2`
- Severity: major · scope motion · 출처 shell-tokens
- Evidence: `"animate-pulse rounded-md bg-surface-muted" … <Loader2Icon className="size-4 animate-spin" /> … data-[starting-style]:scale-[0.98] … activeNavItemRef.current?.scrollIntoView({ behavior: "smooth" …`
- Fix: globals.css에 `@media (prefers-reduced-motion: reduce) { *, ::before, ::after { animation-duration: .01ms !important; transition-duration: .01ms !important; scroll-behavior: auto !important } }`, JS `behavior: "smooth"`는 `matchMedia`로 게이트.

**M15 · Celebratory success — 클립보드 복사에 성공 toast, `완료` 배너; success 채널 불일치(영구 success Alert vs toast vs 무응답)** — anti-patterns § Celebratory success toasts; microinteractions § Copy-to-clipboard 'No toast', § Silent success; gate 16
- Where: `src/components/copy-button.tsx:25-31`; `src/app/admin/features/curated/curation-collections-client.tsx:493-499`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:349-355`; `src/app/admin/features/new/feature-create-client.tsx:778-791`; `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:46-51,125-134`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:690-699,945-962`; `src/app/admin/curations/candidates/curation-candidates-client.tsx:781-786`; `src/app/admin/files/files-client.tsx:572-600`; `src/app/admin/settings/settings-client.tsx:189`
- Severity: major · scope motion · 출처 shell-tokens + pages-features + pages-admin 병합
- Evidence: `await navigator.clipboard.writeText(value); toast.success(\`${label}을(를) 클립보드에 복사했습니다.\`);` · `<Alert><CheckCircle2Icon /><AlertTitle>완료</AlertTitle> … toast.success("복사됨")` · `{deleteUpload.data ? (<Alert><AlertTitle>업로드 삭제됨</AlertTitle>…) : null}`(row는 이미 사라짐, Alert 미해제)
- Fix: 버튼 안에서 아이콘→check + `aria-live="polite"` '복사됨' 2.5s; toast는 실패/미지원 분기만; 새/변경 row를 highlight(배너 대신), 배너는 보이지 않는 bulk CSV commit에만; 페이지는 기존 `CopyButton` 사용; 보이는 효과(delete·reject/promote row 갱신)는 silent, 비가시 async 실행(Dagster load·rescan)만 sonner, 영구 success Alert 금지.

**M16 · Theme plumbing 단절 — `.dark` 토큰 블록·`dark:` variant 존재하나 `.dark`를 설정하는 곳 없음; Sonner가 ThemeProvider 없이 next-themes `useTheme` 호출(toast만 OS scheme), `richColors`가 Sonner 자체 green/red/amber/blue로 도색; `.cn-toast` 참조되나 미정의** — color.md § Dark mode recipe; gate 48
- Where: `src/app/globals.css:30,177-227`, `src/components/ui/sonner.tsx:3-12,31-43`, `src/app/layout.tsx:38`
- Severity: major · scope token · 출처 shell-tokens
- Evidence: `@custom-variant dark (&:is(.dark *)); … const { theme = "system" } = useTheme() … <Sonner theme={theme as ToasterProps["theme"]} … toastOptions={{ classNames: { toast: "cn-toast" } }} … <Toaster position="top-right" richColors />`
- Fix: ThemeProvider(`attribute="class"`) 마운트 + 토글 노출 — 또는 `.dark` 블록·`dark:` variant 삭제; 어느 쪽이든 `richColors` 제거, success/error/warning/info toast는 `toastOptions.classNames`로 프로젝트 status 토큰에서.

**M17 · Generic empty state — DataTable 가운데 `데이터가 없습니다.`, `후보 없음` 등 다음 행동 없는 문자열; EmptyState = dashed-border 가운데 정렬 icon-above-title 타일; EmptyState 두고 페이지마다 bespoke bordered prompt** — interaction-and-states § Loading and empty states; copy.md § Empty states
- Where: `src/components/ui/data-table.tsx:185,461-468`, `src/components/empty-state.tsx:18-30`; `src/app/admin/features/admin-features-client.tsx:109-112,142-147,153`; `src/app/admin/curated-features/curated-features-client.tsx:104-106,190-194,195,216`; `src/app/home-client.tsx:411,502-506`; `src/app/admin/features/new/feature-create-client.tsx:1001`; `src/app/features/features-client.tsx:154,217,783`; `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:93`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:554-560`; `src/app/admin/issues/admin-issues-client.tsx:258-262`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:183-187,327-330,415-418`; `src/app/admin/curations/candidates/curation-candidates-client.tsx:281-283`; `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:504,533`; `src/app/ops/consistency/consistency-client.tsx:216,249`; `src/app/ops/logs/logs-client.tsx:419,469`; `src/app/ops/datasets/datasets-client.tsx:2780-2782`; `src/app/ops/pipeline/events-panel.tsx:432`
- Severity: major · scope copy/component · 출처 shell-tokens + pages-features + pages-admin + pages-ops 병합
- Evidence: `emptyMessage = "데이터가 없습니다."` · `"flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-6 py-10 text-center"` · `<div className="rounded-lg border border-dashed bg-background p-5 text-sm text-muted-foreground">목록에서 업로드를 선택하면 …</div>` · `emptyMessage="후보 없음"` · `<div className="rounded-lg border bg-background p-6 text-sm text-text-secondary">선택된 데이터셋 행이 없습니다.</div>`
- Fix: DataTable에 `emptyState`(title / why / one action) prop; EmptyState는 table frame 안 좌측 정렬, dashed border·icon-above-title 제거; 모든 페이지가 `<EmptyState icon title description action>`(files-client L219-224 방식) 사용, 기본 `데이터가 없습니다.` 금지, 빈 상태 문구 톤 통일 — 무엇이 비었나 + 왜 + 다음 행동(`열린 이슈가 없습니다 — 필터를 전체로 바꿔 보세요`, `행을 선택하면 상세·정책·미리보기가 열립니다`; execution-timeline L789가 모델).

**M18 · Error message — 제목 + raw API 텍스트, 다음 단계 없음; 제목 스타일 4종; `??` 체인이 동시 오류 은폐; DataTable `알 수 없는 오류`에 액션 없음** — copy.md § Error messages
- Where: `src/components/ui/data-table.tsx:230-237,292-300`; `src/app/home-client.tsx:306-316`; `src/app/admin/features/admin-features-client.tsx:883-893`; `src/app/features/features-client.tsx:157-162,641-652`; `src/app/admin/features/curated/curation-collections-client.tsx:485-492`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:317-324`; `src/app/admin/features/new/feature-create-client.tsx:769-776`
- Severity: major · scope copy · 출처 shell-tokens + pages-features 병합
- Evidence: `<AlertTitle>불러오기 실패</AlertTitle><AlertDescription>{error?.message ?? "알 수 없는 오류"}</AlertDescription>` · `<AlertTitle>admin feature 처리 실패</AlertTitle><AlertDescription>{features.error?.message ?? stateMutation.error?.message ?? retireError}</AlertDescription>`
- Fix: 3부 표준(무엇이 깨졌나 · 왜 · 무엇을 할까) + retry/undo 액션, 실패 소스 전부 나열, 제목 패턴 1종(`<대상>을 불러오지 못했습니다`); DataTable에 refetch 연결된 `다시 시도` 버튼 있는 error slot.

**M19 · Loading — skeleton 대신 텍스트(`불러오는 중…`/`loading`), fetch 중 false-empty(`isLoading` 미전달), 단일 블록 skeleton; async 버튼은 disabled만 토글(색 1채널, refresh 아이콘 미회전, 라벨 swap은 cache-target 1곳뿐)** — interaction-and-states § Loading and empty states, § The eight states
- Where: `src/app/admin/files/files-client.tsx:228`, `src/app/admin/backups/backups-client.tsx:349`, `src/app/admin/dedup-reviews/dedup-review-client.tsx:275,284`, `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:202,211`, `src/app/admin/settings/settings-client.tsx:255-259,273-277`, `src/app/admin/curations/candidates/curation-candidates-client.tsx:280-283`; `src/app/home-client.tsx:502-506`(`<Skeleton className="h-[34rem] w-full" />`); ops 텍스트 loader: `src/app/ops/pipeline/page.tsx:14`, `src/app/ops/pipeline/execution-detail-panel.tsx:209`, `src/app/ops/pipeline/events-panel.tsx:331`, `src/app/ops/pipeline/schedule-panel.tsx:882-886`, `src/app/ops/datasets/datasets-client.tsx:2062-2064`; ops 버튼 loading 부재: `src/app/ops/logs/logs-client.tsx:304-312`, `src/app/ops/consistency/consistency-client.tsx:157-160`, `src/app/ops/pipeline/pipeline-client.tsx:506-514`, `src/app/ops/datasets/datasets-client.tsx:2616-2627,1007-1014,1403-1410`, `src/app/ops/pipeline/request-dialog.tsx:1278-1290`, `src/app/ops/pipeline/execution-detail-panel.tsx:601-624`
- Severity: major · scope component · 출처 pages-admin + pages-features + pages-ops 병합
- Evidence: `return <SectionCard title="상세">불러오는 중…</SectionCard>;` · `: "loading"}` · `<DataTable columns={keyColumns} data={keyItems} emptyMessage="저장된 API 키가 없습니다." />`(isLoading 없음 → 로딩 중 빈 메시지) · `<Suspense fallback={<div className="p-6">파이프라인 불러오는 중...</div>}>` · `<Button disabled={systemLogs.isFetching || apiLogs.isFetching} type="button" variant="outline" onClick={refreshAll}><RefreshCwIcon data-icon="inline-start" />새로고침</Button>`
- Fix: 모든 DataTable에 `isLoading` 전달, detail panel/dialog는 `<Skeleton>`(issues L295·offline L518 방식), skeleton은 대체할 콘텐츠 형태로(KPI strip·detail panel·schedule list 블록); Button에 `loading` prop(spinner가 leading icon 대체, 라벨 유지, `aria-busy`, delay-show ≥ 150ms) — 모든 mutation/refetch 트리거에 적용(m4 참조).

**M20 · Colour-as-meaning drift — 진행 상태(running/pending/loading/queued/polling)를 warning 색으로, `--info`는 어떤 상태에도 미매핑, FeatureStateBadges는 축마다 polarity 다름(secondary/outline/destructive), review_required/ambiguous 등 warning성 상태를 destructive로, 비교 후보 B를 destructive red로; ops는 log level/severity/HTTP status code에 generic `StatusBadge`(statusTone에 warning/info/debug 키 없음 → warning·HTTP code 전부 회색)** — color.md § Bans; token semantics; dataviz status discipline
- Where: `src/components/status-badge.tsx:6-52,38-51,55-60`, `src/components/feature-state-badges.tsx:20-32`, `src/app/globals.css:104-106`; `src/app/admin/features/curated/curation-collections-client.tsx:102-118,778-790,1321-1342`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:485-491,609-612`; `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:106-111`; `src/app/admin/dedup-reviews/dedup-review-client.tsx:343-349,358-363`; `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:303-312,322-377`; `src/app/ops/logs/logs-client.tsx:145,196`; `src/app/ops/pipeline/events-panel.tsx:122`; `src/app/ops/pipeline/execution-detail-panel.tsx:503`; `src/app/ops/consistency/consistency-client.tsx:79,111`; `src/app/ops/datasets/datasets-client.tsx:1696`
- Severity: major · scope component/token · 출처 shell-tokens + pages-features + pages-admin + pages-ops 병합
- Evidence: `if (["queued","pending","loading","running","dry-run","reconnecting","polling"].includes(normalized)) { return "warning" as const; }` · `<Badge variant={qualityState === "valid" ? "outline" : "destructive"}>` vs `<Badge variant={publicationState === "published" ? "secondary" : "outline"}>` · `accentClassName="text-red-700" / <div className="text-xs font-medium text-red-700">2차 visitkorea</div>` · `cell: ({ row }) => <StatusBadge status={String(row.original.status_code)} />`
- Fix: progress→info(C2 수정 후 blue), warning은 degraded/needs-attention만, idle은 neutral; 톤 테이블을 한 곳(status-label 모듈)에 발행하고 FeatureStateBadges가 소비('good'은 항상 같은 톤); review_required/ambiguous는 warning; 비교 축은 `--compare-a/--compare-b` 토큰(brand + info), 후보 B에 destructive 금지; `LevelBadge`/`SeverityBadge`(critical·error→destructive, warning→warning, info→info, debug→muted) + `HttpStatusBadge`(2xx muted, 4xx warning, 5xx destructive) 추가, `StatusBadge`는 lifecycle 상태 전용.

**M21 · 페이지 코드의 inline hex / off-token 색 — marker 색 hex 중복, `text-blue-700`/`text-red-700` raw Tailwind(12px red-700은 dark surface에서 4.5:1 미달)** — gate 48
- Where: `src/app/admin/features/admin-features-client.tsx:126-131`; `src/app/admin/curated-features/curated-features-client.tsx:94-100`; `src/app/admin/dedup-reviews/dedup-review-client.tsx:343-349,358-363`; `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:303-312,322-377`
- Severity: major · scope token · 출처 pages-features + pages-admin 병합
- Evidence: `<VWorldMarker lngLat={…} markerColor="#2563eb" selected title={feature.name} />` · `markerColor="#2563eb" … markerColor="#dc2626" … accentClassName="text-blue-700" … accentClassName="text-red-700"`
- Fix: feature kind(또는 `markerColor={null}`)를 넘겨 VWorldMarker가 exported kind palette에서 해석; globals.css에 `--compare-a/--compare-b` 추가해 marker·label에 사용; 페이지 파일에 raw hex 재등장 금지.

**M22 · Badge를 정적 metadata chip으로 남용(uppercase/bold/tracked rows·page·page size·ms·version) — status 색 언어 희석; ops는 row당 badge 4–7개, badge를 counter/KPI로, `-` placeholder까지 badge** — colour-as-meaning; badge 규율; anti-patterns § Icon-tile / restraint axis E
- Where: `src/app/admin/features/admin-features-client.tsx:902-909`; `src/app/home-client.tsx:440-469`; `src/app/admin/features/curated/curation-collections-client.tsx:102-118,778-790,1321-1342`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:485-491,609-612`; `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:106-111`; `src/app/ops/pipeline/execution-timeline.tsx:294-303,344-361`; `src/app/ops/datasets/datasets-client.tsx:2446-2474,2527-2559,1695-1709,2650-2686`; `src/app/ops/logs/logs-client.tsx:345-353`; `src/app/ops/pipeline/pipeline-client.tsx:219-242`; `src/app/ops/consistency/consistency-client.tsx:207-209`
- Severity: major · scope component · 출처 pages-features + pages-ops 병합
- Evidence: `<Badge variant="outline">{formatCount(items.length)} rows</Badge><Badge variant="outline">page {formatCount(pageIndex)}</Badge><Badge variant="outline">page size …</Badge><Badge variant="outline">{durationMs}ms</Badge>` · `<Badge variant="outline">{event.sync_scope}</Badge><Badge variant="outline">{event.operation_key ?? "-"}</Badge> … <Badge variant="outline">page size {pageSize}</Badge>`
- Fix: Badge는 state 전용 — row당 status badge 1개; count/version/key/scope/operation/kind는 muted inline text·mono text 또는 `tabular-nums` dl(별도 column); KPI count는 stat row(M37), placeholder는 badge 금지.

**M23 · Hit target < 44px — 20px HelpTip·CopyButton 아이콘 버튼(::before 확장 없음), 16px checkbox(40×32 확장); ops chip dismiss는 h-6 Badge 안 raw `<button className="ml-1">` + size-3 아이콘(kit ring 미상속, sub-24px), run-detail 토글에 `aria-expanded` 없음** — interaction-and-states § Hit targets; § Bans; gate 26 (검증자: ops 'focus ring 부재'는 오독 — 브라우저 기본 outline은 존재 → critical→major 보정)
- Where: `src/components/help-tip.tsx:31-40`, `src/components/copy-button.tsx:33-45`, `src/components/ui/checkbox.tsx:13`; `src/app/ops/pipeline/execution-timeline.tsx:744-753,759-768`, `src/app/ops/pipeline/events-panel.tsx:451-465`
- Severity: major · scope a11y · 출처 shell-tokens + pages-ops 병합
- Evidence: `"inline-flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground …"` · `"inline-flex size-5 … rounded text-muted-foreground …"` · `size-4 … after:absolute after:-inset-x-3 after:-inset-y-2` · `<button aria-label="배치 필터 지우기" className="ml-1" type="button" …><XIcon className="size-3" /></button>`
- Fix: 20px 글리프 유지 + 두 아이콘 버튼에 `relative before:absolute before:-inset-3`(44px hit box), checkbox pseudo-element `-inset-3.5`; chip dismiss는 `<Button size="icon-xs" variant="ghost">`(kit ring·32px target 상속) 또는 chip 전체가 dismiss control; DagsterRunsPanel `상세` 토글에 `aria-expanded`/`aria-controls`.

**M24 · Tabular data without `tabular-nums` — src 전체에 0건; table cell, pagination count, DetailList 숫자, stat 숫자, count badge 모두 proportional** — anti-patterns § Tabular data without tabular-nums; typography.md § Required features
- Where: `src/components/ui/table.tsx:15,81-90`, `src/components/ui/data-table.tsx:429,499`, `src/components/pagination-bar.tsx:45,93-101`, `src/components/detail-list.tsx:64-69`; `src/app/home-client.tsx:86`(`text-[36px]` stat), `src/app/admin/curated-features/curated-features-client.tsx:206,210`(`<TableCell>{item.sort_order}</TableCell>`); `src/app/admin/files/files-client.tsx:481-484`, `src/app/admin/backups/backups-client.tsx:256-260`, `src/app/admin/offline-uploads/offline-uploads-client.tsx:791-795`, `src/app/admin/curations/candidates/curation-candidates-client.tsx:391-393`, `src/app/admin/dedup-reviews/dedup-review-client.tsx:293-314`, `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:220-237`; `src/app/ops/logs/logs-client.tsx:200-206`, `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:223-252`, `src/app/ops/datasets/datasets-client.tsx:1613-1618,2527-2539`, `src/app/ops/pipeline/pipeline-client.tsx:127`, `src/app/ops/consistency/consistency-client.tsx:178`(`tabular|text-right` src/app/ops 0건)
- Severity: major · scope component · 출처 shell-tokens + pages-features + pages-admin + pages-ops 병합
- Evidence: `<table … className={cn("w-full caption-bottom text-[14px]", className)}> … <span className="text-sm text-muted-foreground">{summary}</span> — 페이지 {page} / {totalPages ?? "-"} · 총 {formatCount(totalCount)}건` · `cell: ({ row }) => formatBytes(row.original.byte_size)`(숫자 column에 proportional 숫자) · `cell: ({ row }) => <span className="font-mono">{row.original.duration_ms}ms</span>`
- Fix: Table/TableCell/PagerShell summary/DetailList dd/DetailMetric/stat figure/count badge에 `tabular-nums`(font-variant-numeric) — DataTable cell에 1회 적용, 숫자 column(duration/count/backlog/failures/size/score)은 `text-right`; mono ID에 `slashed-zero`.

**M25 · Generic AI dashboard 구성 — icon-tile KPI 카드 4-up 동일 그리드, uppercase micro-label, 우측 rail 카드 스택** — anti-patterns § Icon-tile feature card / 3-column feature grid; gates 3, 45
- Where: `src/app/home-client.tsx:48-93,298,318-385,417-509`
- Severity: major · scope page · 출처 pages-features
- Evidence: `<span className="flex size-10 items-center justify-center rounded-xl bg-brand-tint text-brand"><Icon className="size-5" /></span> … <span className="text-[36px] leading-none font-bold">{value}</span>`
- Fix: 아이콘 타일 4개 → typographic stat strip 1개(label + tabular figure + inline status), Feature stat은 2열 span, 아이콘 사각형·uppercase tracking 제거, 서비스 status는 header 아래 compact row(card-in-card 패널 대신).

**M26 · Filter bar — placeholder-as-label, 고정폭 컨트롤 12개 가로 스크롤 strip, 정렬 컨트롤 중복(bar + column header); FilterBar/FilterField 표준이 있는데 무시** — interaction-and-states § Forms ban; restraint
- Where: `src/app/admin/features/admin-features-client.tsx:661-835`(662,665-669,685,703-756,757-769,780-833) vs sortable headers 920-928; `src/app/curated-features/curated-feature-map-client.tsx:511-566`; `src/app/features/features-client.tsx:541-638`; `src/app/admin/issues/admin-issues-client.tsx:811-931`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:970-997`; `src/app/admin/dedup-reviews/dedup-review-client.tsx:492-583`; `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:792-859`; `src/app/admin/settings/settings-client.tsx:218-222`; `src/app/ops/logs/logs-client.tsx:371-380,396-404,428-454,330-344`; `src/app/ops/consistency/consistency-client.tsx:230-242`
- Severity: major · scope component/a11y · 출처 pages-features + pages-admin + pages-ops 병합
- Evidence: `<div className="flex gap-2 overflow-x-auto pb-1"> … <Input … placeholder="name, address, feature_id" /> … <NativeSelect className="w-36 shrink-0"> … <Button>asc</Button><Button>desc</Button>` · `<Input aria-label="issue type" className="w-40 shrink-0" placeholder="issue_type" … />`(가시 라벨 없음) · `<Input aria-label="api log method" placeholder="method" value={apiMethod} …/>`(sibling 패널은 FilterField 사용)
- Fix: 모든 컨트롤을 `<FilterField label=…>`(files-client L653-717 방식)로 — 가시 라벨(방식·경로·최소 상태·페이지 크기), placeholder는 형식만(`126.9,37.5,127.1,37.6`), row는 wrap(스크롤 금지), 정렬은 column header에만, page-size는 pager로.

**M27 · Table density overload — row당 text-xs 4–7줄 스택, `<pre>` JSON dump, inline form** — dense-data 규율
- Where: `src/app/admin/features/curated/curation-collections-client.tsx:1002-1167`(1018-1050,1052-1062,1058-1060,1089-1110,1111-1163), `1392-1466`
- Severity: major · scope component · 출처 pages-features
- Evidence: `<pre className="mt-2 max-w-72 overflow-auto whitespace-pre-wrap break-all rounded bg-surface-subtle p-2 text-xs">{JSON.stringify(item.metadata, null, 2)}</pre> … <FormField labelClassName="sr-only" …/> <Button>Feature 연결</Button>`
- Fix: cell 최대 2줄(name + mono id), metadata/audit/relation/policy는 row detail drawer, `Feature 연결`은 입력이 있는 popover를 여는 row action.

**M28 · Copy consistency — raw English token·snake_case enum이 한글 라벨 옆에(statusLabel/label 사전이 있는데도), 같은 행동에 여러 동사(row `resolve` vs detail `해결`, `retire` vs `종료`, `편집/수정/detail`, `보관 vs 항목 보관 vs 보관 처리`)** — copy.md § Consistency
- Where: `src/app/home-client.tsx:187-209,465-468`; `src/app/admin/features/admin-features-client.tsx:185,403,441,527,539,555,685,753-755,820,832`; `src/app/features/features-client.tsx:179-186,207,227,233,708,865,872`; `src/app/features/[featureId]/feature-detail-page-client.tsx:36`; `src/app/admin/features/new/feature-create-client.tsx:529,904-905,982`; `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:70`; `src/app/admin/features/curated/curation-collections-client.tsx:374,749,782,1092,1098,1101,1159-1160`; `src/app/admin/files/files-client.tsx:683-687`; `src/app/admin/issues/admin-issues-client.tsx:833-853,341,351 vs 716,728`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:978-982,832 vs 860`; `src/app/admin/dedup-reviews/dedup-review-client.tsx:511-529,835-864,929-939 vs 1095`; `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:814-818,565-584`; `src/app/admin/curations/candidates/curation-candidates-client.tsx:192-196,546-583,330 vs 368`; `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:116,127`; `src/app/admin/backups/backups-client.tsx:268,280,86-108`; ops(snake_case 필드명 라벨·미번역 enum·HTTP code·ADR 참조·코드 표현식): `src/app/ops/pipeline/request-dialog.tsx:805,829,885-907,950,1027`, `src/app/ops/datasets/datasets-client.tsx:1971-1976,1419-1423,1231-1237`, `src/app/ops/logs/logs-client.tsx:390-394`, `src/app/ops/pipeline/events-panel.tsx:210-214`, `src/app/ops/pipeline/execution-detail-panel.tsx:484-488,236,625-629`, `src/app/ops/pipeline/execution-timeline.tsx:527-531,358`, `src/app/ops/consistency/consistency-client.tsx:237-241`, `src/app/ops/pipeline/pipeline-client.tsx:528`
- Severity: major · scope copy · 출처 pages-features + pages-admin + pages-ops 병합(ops 부분은 검증자 minor 보정 — API 파라미터를 미러하는 engineer-facing 콘솔)
- Evidence: `header: "kind" / "status" / "progress" / "updated" … <Button>retire</Button> vs confirmLabel: "종료"` · `{ISSUE_STATUSES.map((item) => (<NativeSelectOption key={item} value={item}>{item}</NativeSelectOption>))}` → 옵션은 `open / acknowledged / resolved / ignored`, 옆 badge는 `열림 / 확인됨` · `"채택·거절·무시하거나 병합합니다"` but buttons `accept · reject · merge · ignore` · dt: `created · mode · size` · `<AlertTitle>취소 작업 {cancellation.status}</AlertTitle>` · `"새 요청 생성(201)"` · `label="sync_scope"` · `"… (ADR-064 페이지 ①)."` · `"서버가 mutable=false로 표시한 행"`
- Fix: 용어집 1개 — 모든 column/filter/button/option 한글, enum→label 맵(importStatusLabel/KIND_LABELS 패턴)을 모든 badge·option에, 행동당 동사 1개(수정 · 새로고침 · 보관(ArchiveIcon) · 해결/무시/채택/거절/병합/적재/복원/교체), 영어는 리터럴 식별자(ID/key/sha256)만; ops는 노출 enum 전부 `statusLabel()`, API key는 `help`/hint로 강등, HTTP code·ADR ref·코드 표현식은 operator copy에서 제거.

**M29 · Confirmation 패턴 불일치 — `window.confirm`이 앱 `useConfirm` 옆에, 가역적 archive에 confirm, 비가역 delete(row + 저장 객체)·swap-apply에 confirm/undo/pending 없음, files의 bespoke inline 확인/취소 쌍** — anti-patterns § Confirmation dialogs for reversible actions; destructive-action 규율
- Where: `src/app/admin/features/curated/curation-collections-client.tsx:305-315,374-376`(대조: useConfirm at `src/app/admin/features/admin-features-client.tsx:356-361`, `curation-quarantine-panel.tsx:207-213`); `src/app/admin/offline-uploads/offline-uploads-client.tsx:834-861`; `src/app/admin/backups/backups-client.tsx:258-281,378-434`; `src/app/admin/files/files-client.tsx:351-403` vs `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:150-176`, `src/app/admin/settings/settings-client.tsx:103-115`
- Severity: major · scope component · 출처 pages-features + pages-admin 병합
- Evidence: `if (!window.confirm(\`“${placeName}” 큐레이션 항목을 보관 처리할까요?\`)) { return; }` · `deleteUpload.mutate(upload.upload_id, …)` row에서 직접(`title="업로드 row + 저장 객체 삭제"`) · swap 버튼이 별도 카드에서 executeSwap/applySwap, confirm 없음, pending 중 disabled 없음 · bespoke inline `<Button>확인</Button>`
- Fix: 모든 비가역 행동에 `useConfirm()`(destructive, 동사 라벨, swap-apply는 type-the-id; CSV commit은 removal list 표시), 단일 항목 archive는 optimistic + 8s Undo toast, `isPending` 중 row 버튼 disabled, files의 ad-hoc 확인/취소 삭제.

**M30 · Everything-equal-weight header — outline 버튼 3–6개를 nav로, primary 없음; status 2회 렌더; 페이지 제목을 반복하는 badge** — gate 45 decorative-without-purpose
- Where: `src/app/features/features-client.tsx:851-899,520-529 vs 897-898`; `src/app/curated-features/curated-feature-map-client.tsx:487-501,500 vs 506-509`; `src/app/features/[featureId]/feature-detail-page-client.tsx:18-39`; `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:55-83`
- Severity: major · scope page · 출처 pages-features
- Evidence: `<Badge variant="secondary">Feature 지도</Badge>` under `title="Feature 지도"`, plus six `<Link className={buttonVariants({variant:"outline"})}>`(큐레이션 지도 · Jobs · Update · POI 캐시 대상 · 중복 검토 · 작업 자동화)
- Fix: header는 primary 1 + secondary ≤ 2; cross-link는 sidebar/breadcrumb 또는 overflow menu; status는 toolbar에 1회; title badge 삭제.

**M31 · Flat heading hierarchy — 패널 h2가 body 크기/weight 500, 이름이 `div`, 한 패널에 h2 둘; 24px h1과 14px body 사이 단계 없음** — pre-emit axis B
- Where: `src/app/admin/features/feature-form-sections.tsx:104,205,337,472`; `src/app/admin/features/new/feature-create-client.tsx:872,963,1081`; `src/app/admin/features/admin-features-client.tsx:164,901`; `src/app/admin/curated-features/curated-features-client.tsx:80,180`; `src/app/features/features-client.tsx:126,167`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:436,653,669`
- Severity: major · scope structure · 출처 pages-features
- Evidence: `<h2 className="font-medium">기본 정보</h2> … <div className="text-lg font-semibold">{feature.name}</div> … <div className="font-medium">위치 확인</div>`
- Fix: heading role 2개 정의(section h2 ≈18px/600, panel h3 14px/600), 실제 heading 요소 사용; entity name은 h2/h3(div 금지).

**M32 · Master-detail idiom drift — 같은 macro인데 rail 폭/breakpoint/side가 페이지마다 다름(24/26/28/30rem, xl vs 2xl, 좌/우), review 페이지는 dialog `max-w-6xl`, curation은 5카드 수직 스택 아래 detail** — structure axis F
- Where: `src/app/home-client.tsx:387`; `src/app/admin/features/admin-features-client.tsx:897`; `src/app/admin/features/new/feature-create-client.tsx:836`; `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx:154`; `src/app/admin/features/curated/curation-collections-client.tsx:1237`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:812`; `src/app/admin/files/files-client.tsx:719`; `src/app/admin/backups/backups-client.tsx:340`; `src/app/admin/issues/admin-issues-client.tsx:935`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:923`; `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:385`; `src/app/admin/dedup-reviews/dedup-review-client.tsx:262-268`; `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:186-195`; `src/app/admin/curations/candidates/curation-candidates-client.tsx:754-847`
- Severity: major · scope structure/page · 출처 pages-features + pages-admin 병합
- Evidence: `xl:grid-cols-[minmax(0,1fr)_24rem] · _26rem · _28rem · _30rem · 2xl:grid-cols-[minmax(0,1fr)_28rem] · xl:grid-cols-[24rem_minmax(0,1fr)] · <DialogContent className="max-w-6xl">`
- Fix: rail 토큰 1개(`--rail`/`--pane-w` ≈ 26rem) + breakpoint 1개, inspector는 항상 우측; review 페이지도 list + right pane, dialog는 compare-only view에만; curation detail은 list 옆으로.

**M33 · 공용 CursorPager/OffsetPager 옆에 hand-rolled pager** — 반복 bespoke layout
- Where: `src/app/admin/files/files-client.tsx:725-747`, `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:476-497`
- Severity: major · scope component · 출처 pages-admin
- Evidence: `<Button … onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}>이전</Button><span className="text-xs text-muted-foreground">{offset + 1}–{…}</span>`
- Fix: `<OffsetPager>`(files), `<CursorPager>`(poi)로 교체 — aria-label·disabled 로직·summary copy 통일.

**M34 · Mouse-only affordance — raw `TableRow`에 onClick만, tabIndex/keyboard handler 없음(DataTable canon 우회)** — hover/keyboard parity
- Where: `src/app/admin/curations/candidates/curation-candidates-client.tsx:285-339`
- Severity: major · scope a11y · 출처 pages-admin
- Evidence: `<TableRow className="cursor-pointer" data-state={…} onClick={() => onSelect(candidate.candidate_id)}>`
- Fix: `<DataTable onRowClick isRowActive isLoading>`으로 렌더(tabIndex, Enter/Space, skeleton row 내장).

**M35 · Disabled without explanation / hover-only affordance — disabled primary action에 사유 없음; 사유가 hover `title`에만 있는데 `disabled:pointer-events-none`이라 도달 불가; ops는 핵심 컨텍스트(SLA/freshness 사유·schedule 상태·issue severity·live error)가 `title=`에만, replay/reconcile은 사유 미입력 시 disabled인데 안내는 검증 후에만** — interaction-and-states § Bans; anti-patterns § Hover-only affordances
- Where: `src/app/admin/features/curated/curation-collections-client.tsx:669-682`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:643-666`; `src/app/features/features-client.tsx:563-572`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:814-861`; `src/app/ops/datasets/datasets-client.tsx:1591,2448,2513,2549,2657`; `src/app/ops/pipeline/schedule-panel.tsx:955`; `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:497-504,562-568,580-588,136-141`
- Severity: major · scope a11y · 출처 pages-features + pages-admin + pages-ops 병합
- Evidence: `disabled={!csvFile || !importReport?.data.dry_run || importReport.data.invalid_rows > 0 || importReport.data.issues.length > 0 || importCsv.isPending}` · `<Button … disabled={launchLoad.isPending || !loadEnabled} title={loadEnabled ? "load" : "CSV/TSV는 validation 완료 후 load 가능"} …>` · `<span className="flex flex-wrap items-center gap-1" title={freshnessReason(row.original.freshness)}>` · `const replayDisabled = selectedDeadLetter === null || replayReason.trim().length === 0 || replayPending; … setReasonError("replay 사유를 입력하세요.")`
- Fix: 버튼 아래 한 줄 helper(`오류 N행을 먼저 해결하세요`) 또는 HelpTip로 가시화, 또는 enabled 유지 + 클릭 시 validate; disabled 컨트롤의 `title` 금지; 사유는 가시 secondary text(freshness column에 자리 있음) 또는 focus-trigger `Tooltip`; 사유 입력 필드에 `hint="사유를 입력하면 활성화됩니다"` — datasets `refreshDisabledReason`/`disabledReason` 패턴(L1206-1264)이 모델.

**M36 · Invented metric / false zero — KPI 타일이 query loading/absent 중 `0` 렌더(ops 콘솔에서 all-clear로 읽힘); `formatCount`가 `value ?? 0`** — anti-patterns § Invented metrics; gate 46 (검증자: 실데이터의 loading 상태 누락이지 조작 stat 아님 → critical→major 보정)
- Where: `src/app/ops/consistency/consistency-client.tsx:178-180`, `src/app/ops/pipeline/pipeline-client.tsx:186-205`, `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:321-359`, `src/lib/format.ts:19-21`
- Severity: major · scope component · 출처 pages-ops
- Evidence: `value={formatCount(data?.active_operations ?? 0)} … export function formatCount(value){ return compactNumberFormatter.format(value ?? 0); }`(isLoading/isError guard 없음)
- Fix: `formatCount`는 null/undefined에 `—`, 숫자 슬롯은 query resolve 전 `<Skeleton>`; 미지 telemetry를 0으로 coalesce 금지.

**M37 · KPI/summary 표기 4종 + 페이지 컨테이너 chrome 2종 + LiveBadge 톤 2종 — sibling ops 페이지 간 시스템 불일치** — gate 8 structural fingerprint; hierarchy axis B
- Where: `src/app/ops/pipeline/pipeline-client.tsx:112-134,185-245,503-505`, `src/app/ops/consistency/consistency-client.tsx:175-196`, `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:334-375`, `src/app/ops/datasets/datasets-client.tsx:2650-2686,1955,2655-2669`
- Severity: major · scope page · 출처 pages-ops
- Evidence: pipeline `<p className="mt-1 text-[36px] leading-none font-bold">` · consistency `<div className="mt-1 text-2xl font-semibold">` · cache `<Card size="sm"><CardTitle>{n} 개` · datasets `<Badge>행 {n}</Badge>`; live는 pipeline solid-brand vs datasets outline
- Fix: `StatStrip` 1개(label + tabular figure + caption — M25 홈 stat strip과 같은 컴포넌트) + section 컨테이너 1종(SectionCard, M7)을 5페이지 공용; `LiveBadge` 1개에 고정 톤 맵.

**M38 · Truncation without disclosure — `line-clamp-2`가 `whitespace-nowrap` `<td>` 안이라 wrap 불가 → 로그/이벤트 메시지가 ellipsis 없이 1줄 clip, row detail 없음** — hover-only / hierarchy
- Where: `src/app/ops/logs/logs-client.tsx:154-157`, `src/app/ops/pipeline/events-panel.tsx:160-163`, `src/app/ops/consistency/consistency-client.tsx:138`, `src/components/ui/table.tsx:86`
- Severity: major · scope component · 출처 pages-ops
- Evidence: `<div className="max-w-96"><div className="line-clamp-2">{row.original.message}</div></div>` — TableCell = `"px-3 py-2.5 align-middle whitespace-nowrap"`
- Fix: message cell `whitespace-normal`(clamp 동작), 로그 row에 expand/detail affordance(row click → detail pane 또는 inline expansion)로 전문 도달.

**M39 · Feedback far from trigger / alert wall — mutation 결과·오류가 패널 상단 Alert 스택(최대 8슬롯), 컨트롤은 하단; schedule row `scrollIntoView(center)`가 결과를 화면 밖으로** — microinteractions § Toast / feedback placement
- Where: `src/app/ops/pipeline/schedule-panel.tsx:637-812,364-368`, `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:644-665`, `src/app/ops/pipeline/request-dialog.tsx:1254-1267`
- Severity: major · scope page · 출처 pages-ops
- Evidence: `{lastResult ? <ScheduleCommandResultAlert…/>} {failedResult ? …} {patchSchedule.isError ? …} {commandSchedule.isError ? …} {frozenScheduleMutation ? …} {recoveryClaim ? …} {resolveClaim.isSuccess ? …} {resolveClaim.isError ? …}`
- Fix: 명령 결과는 해당 schedule row inline(toolbar 아래 status line), 패널당 blocking Alert 슬롯 1개, 실패는 sonner; cache-target replay/reconcile 결과는 Recovery 카드 안에.

**M40 · Hand-rolled controls beside the ui kit — raw `<textarea>`/`<input type=checkbox>`/`<pre>`+`JSON.stringify`가 Textarea·Checkbox·JsonViewer 옆에(focus ring 상이)** — system inconsistency
- Where: `src/app/ops/pipeline/request-dialog.tsx:916-921,960-965,1046-1050,1147`, `src/app/ops/datasets/datasets-client.tsx:837-841,1185-1187,1767-1769,887`; `src/app/admin/backups/backups-client.tsx:393-432`
- Severity: major · scope component · 출처 pages-ops + pages-admin 병합
- Evidence: `<textarea aria-label="feature id 목록" className="min-h-24 rounded-md border bg-background p-2 font-mono text-xs" … />` · `<p>매칭 대상: {JSON.stringify(preview.matched_scope)}</p>` · `<label className="flex items-center gap-2 text-sm"><input checked={executeSwap} type="checkbox" …/>swap command 실행</label>`
- Fix: ui/Textarea(bg-card, border-input, brand ring)·ui/Checkbox(FormField 라벨)·JsonViewer(copyable, maxHeight)로 전부 교체; backups의 execute/apply 토글은 그 행동의 confirm dialog 안으로(M29).

**M41 · Row action soup — row/패널당 equal-weight 버튼 5–6개, merge 서브상태가 table cell 안에서 버튼 추가 확장; schedule row마다 사유 Input + 4버튼 툴바가 둥근 패널 안, run/start도 dialog confirm** — hierarchy axis B; restraint; anti-patterns § Confirmation dialogs
- Where: `src/app/admin/dedup-reviews/dedup-review-client.tsx:748-866`, `src/app/admin/issues/admin-issues-client.tsx:332-389,704-730`; `src/app/ops/pipeline/schedule-panel.tsx:891-1009,378-386`
- Severity: major · scope component · 출처 pages-admin + pages-ops 병합(ops 부분은 minor)
- Evidence: `<Button …>detail</Button><Button …>accept</Button><Button …>reject</Button><Button variant="default">merge</Button><Button variant="ghost">ignore</Button>` … `master 선택`이 같은 셀에 A/B/자동 선정/취소 렌더 · `<FormField … label="명령 사유 (선택)" placeholder="시작·중지·reset·즉시 실행 감사 로그에 기록" …/>` inside `scheduleItems.map`
- Fix: row당 primary 1 + secondary 1, 나머지는 `⋯` overflow menu; master 선택은 detail dialog에서; 감사 사유는 confirm dialog 안 필드 1개(한 곳), schedule row는 name + cron + status + compact toolbar의 plain list/table.

**M42 · Twin-page duplication — dedup/enrichment가 helper·dialog·filter grid·pager·JSON block을 복사, 그룹 안 JSON 렌더러 4종** — 반복 bespoke layout
- Where: `src/app/admin/dedup-reviews/dedup-review-client.tsx:67-167,243-374,478-628`, `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:67-157,159-423,723-859`, `src/app/admin/issues/admin-issues-client.tsx:69-75`, `src/app/admin/curations/candidates/curation-candidates-client.tsx:151-157`
- Severity: major · scope component · 출처 pages-admin
- Evidence: `function JsonBlock … <pre className="max-h-52 overflow-auto rounded-md bg-muted p-3 text-xs">`(dedup) vs `<JsonViewer value=… maxHeight="md" copyable />`(enrichment) vs `<pre className="max-h-72 … rounded-lg bg-muted p-3">`(issues)
- Fix: `ReviewCompareDialog`·`ScoreMetricStrip`·`ReviewFilterBar` 추출, JSON은 항상 `JsonViewer` — 구현 1개, 모양 1개.

**M43 · Form label style drift — 한 그룹에 label 처리 5종(raw `<label>` 3종 vs FilterField vs FormField)** — component drift
- Where: `src/app/admin/backups/backups-client.tsx:384-386`, `src/app/admin/offline-uploads/offline-uploads-client.tsx:254,275`, `src/app/admin/curations/candidates/curation-candidates-client.tsx:180-181,224-225,457-458,517-518` vs `src/app/admin/files/files-client.tsx:654`(FilterField), `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:391-449`(FormField)
- Severity: major · scope component · 출처 pages-admin
- Evidence: `<label className="flex flex-col gap-1 text-sm">backup id …` / `<label className="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">` / `<label className="space-y-1 text-sm"><span className="font-medium">`
- Fix: 폼 컨트롤은 FormField/FormSelect, 필터는 FilterField — raw `<label>` 변형 삭제.

### 2.3 Minor

**m1 · Header가 한 장소에 식별자 4개 스택 — section Badge, raw route path(mono), breadcrumb, h1** — copy.md § Principles(no redundancy); debug artefact as UI copy
- Where: `src/components/admin-shell.tsx:310-349` · Severity: minor · scope copy · 출처 shell-tokens
- Evidence: `{sectionBadge ? <Badge variant="secondary">{sectionBadge}</Badge> : null} <span className="break-all font-mono text-[12px] text-text-secondary">{pathname}</span> … <Breadcrumb>…</Breadcrumb> … <h1 …>{title}</h1>`
- Fix: breadcrumb + h1(+ description)만; section badge 삭제(breadcrumb가 그룹 보유), raw pathname은 copyable 'link' affordance 또는 HelpTip 뒤로.

**m2 · Typographic punctuation·generic 버튼 라벨 — null glyph·pager 구분자로 `-` hyphen, 기본 confirm 라벨 `확인`(=OK); ASCII stand-in(`...`, `>=`, straight quote)·raw 데이터 glyph(lucide 버튼 안 `✓`, `∅`, `String(bool)`)** — copy.md § Proper typography, § Buttons; anti-patterns § Three periods; gate 30 icon voice
- Where: `src/components/detail-list.tsx:42`, `src/components/pagination-bar.tsx:53,95`, `src/components/json-viewer.tsx:15`, `src/components/status-badge.tsx:73`, `src/components/confirm-dialog.tsx:75,83`; `src/app/admin/settings/settings-client.tsx:62`, `src/app/admin/dedup-reviews/dedup-review-client.tsx:73-75,777,789`, `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:58-60`, `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:154`, `src/app/admin/curations/candidates/curation-candidates-client.tsx:832-834`; `src/app/ops/pipeline/page.tsx:14`, `src/lib/format.ts:27`
- Severity: minor · scope copy · 출처 shell-tokens + pages-admin + pages-ops 병합
- Evidence: `const rawValue = item.value ?? "-"; … if (value === null || value === undefined) return "-"; … {pending?.confirmLabel ?? "확인"}` · `label: "score >= 90"` · `title: \`'${target.target_key}' 대상을 삭제할까요?\`` · `{transition.from_review_state ?? "∅"}` · `\`${value.slice(0, size)}...\``(shortId)
- Fix: 빈 값은 `—`(U+2014), pager는 thin-space `/` 또는 `·`; caller가 동사 라벨(삭제 / 병합 / 실행) 필수, 기본 `confirmLabel`은 dev에서 throw; `…`(U+2026)/`≥`/curly quote, `✓`는 lucide `CheckIcon`, boolean은 `일치/불일치` 라벨.

**m3 · Latin small-caps 레시피를 한글에 — `uppercase tracking-[0.05em]` 11–12px bold가 badge·th·nav 그룹 라벨·error eyebrow·card eyebrow에; 한글엔 무효과 + 원치 않는 tracking, 혼합 라벨은 반만 대문자** — typography.md § Headings rules; § Body rules ≥ 12px; anti-patterns § Eyebrow on every section
- Where: `src/components/ui/badge.tsx:8`, `src/components/ui/table.tsx:73`, `src/components/ui/data-table.tsx:448`, `src/components/admin-shell.tsx:265`, `src/components/app-error-panel.tsx:72`, `src/components/status-badge.tsx:67`; `src/app/home-client.tsx:66,431,454`, `src/components/login-form.tsx:69-70`; ops h3/label: `src/app/ops/pipeline/execution-detail-panel.tsx:313,418,436,473,587`, `src/app/ops/pipeline/pipeline-client.tsx:124,208`
- Severity: minor · scope token · 출처 shell-tokens + pages-features + pages-ops 병합(검증자: eyebrow가 아닌 section heading 자체의 label 스타일 → major→minor 보정)
- Evidence: `text-[12px] font-bold tracking-[0.05em] whitespace-nowrap uppercase … "gap-1.5 text-[11px]" … "hidden px-3 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-text-secondary uppercase lg:block"` · `<CardTitle className="text-[12px] font-bold tracking-[0.05em] text-text-secondary uppercase">` · `<h3 className="text-xs font-bold tracking-[0.05em] text-muted-foreground uppercase">요청 payload</h3>`
- Fix: 한글 포함 라벨에서 `uppercase`/tracking 제거 — 12px 600 `tracking-normal`; `tracking-wide`는 mono로 렌더되는 순수 Latin 코드에만; card label은 normal case sm step; ops sub-heading은 normal-case 12–13px semibold text-secondary.

**m4 · Disabled를 색 하나로만 + cursor 제거 — `disabled:pointer-events-none`이 `cursor: not-allowed` 제거, opacity 없음, `#b5bdb7` on `#e3e8e2`/`#fff` ≈ 1.5–1.9:1이라 disabled pager 라벨 판독 불가** — gate 39 'disabled by one channel'; interaction-and-states § Eight states
- Where: `src/components/ui/button-variants.ts:4,9`, `src/components/pagination-bar.tsx:103-142`, `src/app/globals.css:100`
- Severity: minor · scope component · 출처 shell-tokens
- Evidence: `disabled:pointer-events-none disabled:text-text-disabled … default: "bg-brand text-brand-foreground hover:bg-brand/90 disabled:bg-surface-muted"`
- Fix: `disabled:opacity-55 disabled:cursor-not-allowed`(pointer-events-none 제거), 라벨 색은 판독 가능하게; `loading` prop으로 라벨→inline spinner(조용히 disable 금지).

**m5 · Generic auth card — 전체 뷰포트 중앙 hand-rolled 카드, icon-in-tinted-square + eyebrow 워드마크** — icon-tile; gate 6(soft)
- Where: `src/components/login-form.tsx:62-72` · Severity: minor · scope page · 출처 pages-features
- Evidence: `<section className="w-full max-w-sm rounded-lg border border-surface-muted bg-card p-6 shadow-[var(--shadow-card)]"> <span className="flex size-10 … rounded-lg bg-brand-tint text-brand"><LockKeyholeIcon …/></span>`
- Fix: `Card` primitive 재사용, 아이콘 타일 제거, 워드마크는 좌측 정렬 h1 위 plain text; 나머지 유지.

**m6 · Map view chrome — tab bar 안 debug 좌표 readout, 비토큰 `shadow-lg` floating panel, 중복 inline style, magic vh 높이** — restraint; token
- Where: `src/app/features/features-client.tsx:707-710,121,714-723,762,772,795,900`; `src/app/curated-features/curated-feature-map-client.tsx:598-601,219,503,605,636,659`
- Severity: minor · scope page · 출처 pages-features
- Evidence: `<span className="text-sm text-muted-foreground">center {viewport.lon.toFixed(4)}, … · z {viewport.zoom.toFixed(1)}</span> … className="… shadow-lg" … style={{ height: "100%", inset: 0, position: "absolute", width: "100%" }}`
- Fix: readout은 map 모서리 mono chip, `shadow-[var(--shadow-elevated)]`, 중복 style prop 삭제, map은 `flex-1/min-h-0`(`calc(100vh-Nrem)` 금지).

**m7 · Selectable list tile을 3가지로 구현** — component drift
- Where: `src/app/admin/features/curated/curation-collections-client.tsx:729-756`; `src/app/admin/features/curated/curation-quarantine-panel.tsx:391-418`; `src/app/admin/features/new/feature-create-client.tsx:928-955`; `src/app/home-client.tsx:489-500`
- Severity: minor · scope component · 출처 pages-features
- Evidence: `"w-full rounded-xl border p-3 … border-brand bg-brand-tint"` vs `"rounded-md border px-3 py-2 … border-primary bg-primary/10 text-primary"` vs `"rounded-xl bg-surface-subtle … hover:bg-brand-tint"`
- Fix: `SelectableRow` primitive 1개: borderless row, hover `bg-surface-subtle`, selected `bg-brand-tint + ring-1 ring-brand`, explicit focus-visible.

**m8 · Developer telemetry가 UI chrome에 — ms badge, backticked route path, `Issue table`/`{n} rows`** — invented-metric / restraint axis
- Where: `src/app/admin/issues/admin-issues-client.tsx:926-931,939-942`; `src/app/admin/offline-uploads/offline-uploads-client.tsx:994-996,446`; `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:470-474`; `src/app/admin/dedup-reviews/dedup-review-client.tsx:617`; `src/app/admin/enrichment-reviews/enrichment-review-client.tsx:731`
- Severity: minor · scope copy · 출처 pages-admin
- Evidence: `<Badge …>{issues.data?.meta.duration_ms ?? 0}ms</Badge> … <div className="font-medium">Issue table</div><div …>\`/admin/issues\` keyset cursor 목록</div> … {n} rows`
- Fix: ms badge·route path 제거, row count는 pager summary(`이 페이지 N건 · 총 N건`)로, 패널 제목은 사람 말(`이슈 목록`).

**m9 · Hand-rolled definition list — `DetailList`가 있는데 grid dl 4종(라벨 열 폭 9rem/8rem/auto)** — 반복 bespoke layout
- Where: `src/app/admin/backups/backups-client.tsx:84-113`, `src/app/admin/offline-uploads/offline-uploads-client.tsx:171-178,201-232`, `src/app/admin/issues/admin-issues-client.tsx:310-330`, `src/app/admin/curations/candidates/curation-candidates-client.tsx:374-399`, `src/app/admin/dedup-reviews/dedup-review-client.tsx:160-167`
- Severity: minor · scope component · 출처 pages-admin
- Evidence: `<div className="grid gap-1 sm:grid-cols-[9rem_1fr]">` vs `sm:grid-cols-[8rem_1fr]` vs `grid-cols-[auto_1fr]` vs `<DetailList items={items} columns={1} />`(files L309)
- Fix: 모든 key-value 패널을 `<DetailList items>`(mono/copyable/help 지원)로 — 라벨 열 폭 1개.

**m10 · Search-as-you-type without debounce — 키 입력마다 refetch** — microinteractions § Search-as-you-type(250ms)
- Where: `src/app/admin/files/files-client.tsx:655-660,413-427`
- Severity: minor · scope page · 출처 pages-admin
- Evidence: `onChange={(event) => patch({ q: event.target.value })}` → listParams(useMemo) → `useManagedFiles` refetch on every keystroke
- Fix: `q`를 `useDeferredValue`(issues/dedup 방식) 또는 250ms debounce 후 listParams에.

**m11 · Destructive colour diluted — retry(`동일 요청 재확인`)·`claim 해제`가 `variant="destructive"`, replay confirm에 `destructive: true`, form error Alert에 destructive** — color.md § Use of the accent; colour-as-meaning (검증자: `중지`·replay는 red 방어 가능 → major→minor 보정)
- Where: `src/app/ops/pipeline/schedule-panel.tsx:699-710,770-788,961-972`, `src/app/ops/cache-target-streams/cache-target-streams-client.tsx:143-149`, `src/app/ops/pipeline/request-dialog.tsx:1106-1111`
- Severity: minor · scope component · 출처 pages-ops
- Evidence: `<Button … variant="destructive" onClick={retryFrozenScheduleMutation}>동일 요청 재확인</Button>` · `confirm({ title: \`… event를 replay할까요?\`, … destructive: true })`
- Fix: destructive는 비가역 손실(cancel/stop)에만; retry·claim resolution·replay는 default/outline, validation 안내는 기본 Alert 톤.

**m12 · Canonical-write form에 실제 값 prefill(서울시청 lon/lat, 서울 bbox) — placeholder 대신 값** — interaction-and-states § Forms(placeholder는 형식만)
- Where: `src/app/ops/pipeline/request-dialog.tsx:158-164`
- Severity: minor · scope component · 출처 pages-ops
- Evidence: `const [lon, setLon] = useState("126.9780"); const [lat, setLat] = useState("37.5665"); const [radiusKm, setRadiusKm] = useState("5");`
- Fix: 빈 값 + `placeholder="예: 126.9780"` — operator가 입력하지 않은 scope를 제출할 수 없게.

## 3. 보존할 것 (그룹 strengths 병합, 중복 제거)

1. **토큰 규율은 실제** — 29 ui primitives + shell 컴포넌트 + ops 11k 라인에 inline hex/oklch/rgb 0건(`bg-black/45` 1건, 페이지 marker hex 2곳만 예외), shadow 토큰화, lucide 단일 아이콘, emoji/gradient/blob/glassmorphism 0건, 모든 중립색이 brand-tinted green — `globals.css` 하나로 re-theme 가능.
2. **AA 대비를 의도한 status 색** — `--success/--warning/--destructive`가 light surface에서 4.5:1 clear, 근거가 CSS 주석에 문서화; `StatusBadge`는 색 + dot + 한글 라벨 병행(의미가 색에만 타지 않음).
3. **a11y가 primitives에 내장** — Alert가 severity별 role/aria-live, FormField가 id/aria-describedby/aria-invalid/aria-required, DataTable가 aria-sort·virtualised aria-rowcount/rowindex·keyboard row activation·clickable row focus ring.
4. **모션은 절제되고 형태가 맞음** — overlay 100–150ms scale-0.98/opacity 표준 curve, input border-width가 default/focus/invalid에서 일정, bounce·hover:scale·gradient·scroll-reveal 없음.
5. **task 지향의 정직한 copy** — nav 라벨이 일(중복 검토, 보강 검토, 정합성 점검), AppErrorPanel이 what/why/what-to-do + 다시 시도 + 이전 화면 + 접이식 details, HelpTip이 긴 설명을 inline hint 밖으로(hover tooltip + touch popover); 한글 copy가 curly quote·em-dash·ellipsis 사용; ops의 오류·충돌 copy도 what/why/what-to-do + inline 복구 액션(request-dialog 409 → `기존 활성 요청 열기` L1112-1134, datasets 상태 실패 → `다시 확인`/`파이프라인에서 보기` L1493-1520), datasets 정책 편집기는 한글 라벨 + 필드별 HelpTip + 사람 말 hint(`86400초 = 24시간`, L704-844) — request dialog의 모델.
6. **공유 dense-data 어휘 존재** — DataTable(shape-matched skeleton row), FilterBar/FilterField, PagerShell(aria-labelled), DetailList(dl/dt/dd + mono + copy), JsonViewer, SectionCard, EmptyState, FormField/FormSelect/FormTextArea, CopyButton — 27페이지 대신 primitives 십여 개만 restyle하면 되고, 신규 curation 코드는 이미 이 canon을 사용.
7. **프레임 일관성** — 모든 페이지가 같은 AdminShell(h1 + breadcrumb + actions slot) 안, toolbar→list→inspector 한 리듬 — ops 콘솔로서 구조적으로 정합.
8. **dense-data 기반이 실제** — 대용량 bbox 리스트 virtualization, keyset CursorPager, row-click selection + `isRowActive`, 저 zoom server-cluster fallback; ops는 URL이 selection/tab의 정본이고 close 시 originating row로 focus 복귀(datasets L2285-2340, pipeline L478-497), detail 토글에 aria-controls/aria-expanded/aria-pressed(datasets L204-224).
9. **정직한 상태** — `부분 결과` truncation badge(설명 title 포함), map cluster-mode hint, VWorld-key alert, 지어낸 metric 0건(단 loading 중 false-zero는 M36).
10. **파괴적 흐름은 useConfirm + 결과 명시 copy**(예: `provider 재적재로 다시 활성화되지 않도록 잠급니다.`) — 패턴이 이미 있어 M29는 '확산'이지 '발명'이 아님.
11. **Fail-closed 사유가 가시 copy로** — datasets `refreshDisabledReason`(L1206-1264)·`policyMutationBlockedReason`(L1934-1950), timeline prerequisite hint(L592-599): 조용한 disable 대신 사유를 써 준다 — 보존하고 확산(M35의 모델).
12. **Live 데이터가 operator 아래에서 재정렬되지 않음** — execution-timeline이 head poll로 newCount를 계산해 `새 실행 N건 — 첫 페이지로`(L233-261, L710-720)를 제안하고 자동 refresh 안 함; ops 11k 라인에 toast/transition-all/hover-scale/animation 0건.

## 4. Redesign 입력 (`hallmark redesign` — multi-page flow → `design.md` 선행)

### 4.1 권장 genre: **editorial-utilitarian**
dense table·mono ID·한글 라벨이 지배하는 내부 ops 콘솔이라 위계는 그림자·카드가 아니라 서체·hairline·정렬로 만들어야 하고(C3/M6/M8/M9의 fix 방향과 동일), 현 상태의 modern-minimal(둥근 흰 카드 + 넓은 여백)이 곧 "generic AI admin" 지문이다.
따라서 flush band + 1px rule + 2단계 radius + Pretendard/Geist Mono 조판의 editorial-utilitarian이 기존 토큰 강점(§3 1·2·6)을 그대로 살리면서 지문을 바꾸는 최단 경로.

### 4.2 잠글 토큰 표면 (KEEP — 이름 유지, 값만 조정)
- 색: `--brand`, `--brand-tint`, `--brand-foreground`, `--surface-muted`, `--surface-subtle`, `--text-primary`, `--text-secondary`, `--text-tertiary`(값 ≥ 4.5:1로), `--text-disabled`, `--success`, `--warning`, `--destructive`, `--info`(값 어둡게), `--border`.
- 깊이·형태: `--shadow-card`, `--shadow-card-hover`, `--shadow-elevated`, `--shadow-modal`, `--radius`(6px로).
- 서체: `--font-sans`(Pretendard Variable + Geist Latin fallback으로 재바인딩).
- shadcn alias(`--background/--primary/--ring/--card/--popover/--muted-foreground/--foreground`)는 유지하되 `@theme`에서 위 프로젝트 이름으로 매핑만(M5) — 컴포넌트 public 어휘에서 제외.
- 추가(신규, 이름 제안): `--brand-hover`, `--success-tint/--warning-tint/--info-tint/--destructive-tint`, `--overlay`, `--compare-a/--compare-b`, `--font-mono`, `--control-h/--control-h-sm`, `--radius-control/--radius-panel`, `--rail`(또는 `--pane-w`), `--text-2xs…--text-2xl`.

### 4.3 최고 leverage 이동 (leverage/effort 순)
1. **`globals.css` 토큰 패스 (1파일, 최대 파급)** — 포커스 레시피 1종(C1), `--info/--text-tertiary` 대비(C2), 불투명 tint 토큰(M4), radius 2값(M6), ratio type scale(M3), control 높이 2값(M12), `prefers-reduced-motion`(M14), `a` 규칙 prose 스코프(M10), `--font-mono`(M2), `.dark`/Sonner 결정(M16).
2. **서체 교체** — `layout.tsx` + `globals.css`: Pretendard Variable(next/font/local) + Geist Mono(M2). 페이지 코드 무변경으로 지문의 절반이 바뀜.
3. **Shell 재구성** — `admin-shell.tsx` 1파일: typographic 워드마크·status strip·small-caps+rule nav·flush header band(M9), `<main>` 범위·skip link·`aria-current`(M11), 식별자 4→2(m1), 카드 레시피 → `<Card>`(M8).
4. **Primitives 정비 (ui/ 십여 파일)** — button-variants(높이·no-underline·disabled·loading), input/select size, card(rest shadow 제거·`data-interactive`), badge(uppercase 제거·tabular), table(`tabular-nums`), field(단일 message slot), copy-button(toast 제거·hit box), help-tip/checkbox hit box, tabs transition, sonner classNames, empty-state 좌측 정렬, data-table `emptyState`/error slot/`isLoading`, pagination `—`/`·`, confirm-dialog 동사 라벨 강제.
5. **상태·색 의미 테이블 1곳** — status-label 모듈에 tone table + enum→label 사전 발행, StatusBadge/FeatureStateBadges/모든 option·column이 소비(M20/M28) + `--compare-a/b`로 marker/label(M21).
6. **페이지 컨테이너·필터·confirm 수렴 (기계적, 파일 多)** — bespoke box→SectionCard(M7), 필터→FilterField(M26), pager→Offset/CursorPager(M33), TableRow→DataTable(M34), window.confirm/직접 mutate→useConfirm(M29), disabled 사유 가시화(M35), skeleton/isLoading(M19), EmptyState(M17), 3부 error(M18), raw textarea/checkbox/pre→ui kit(M40), raw label→FormField/FilterField(M43), grid dl→DetailList(m9), review twin 추출(M42), row action overflow(M41), debounce(m10).
7. **card-in-card 해체 + master-detail 통일** — quarantine/collections/home/features/map/candidates/files/offline-uploads + ops logs/consistency/datasets/cache-target의 containment 1층(C3), `--rail` 1값·우측 inspector·review dialog→pane(M32), SelectableRow primitive(m7).
8. **홈·헤더 재구성** — KPI 아이콘 타일→typographic stat strip(M25), 헤더 primary 1 + secondary ≤ 2·title badge 삭제(M30), heading role 2종(M31), 로그인 카드 단순화(m5), map chrome 정리(m6).
9. **ops 데이터 표시 규율** — `StatStrip`/`LiveBadge` 1종(M37, M25와 공용) + `formatCount` `—`/skeleton(M36), Level/Severity/HttpStatus badge(M20), 로그·테이블 mono→식별자만 + `tabular-nums`/`text-right`(M2/M24), message cell wrap + row detail(M38).
10. **ops 피드백·상태 copy** — 결과 inline on row + Alert 슬롯 1개(M39), Button `loading`(M19), 사유·차단 상태를 가시 텍스트로(M35 — datasets disabledReason 패턴 확산), destructive는 비가역만(m11), dead-letter/blocked 빈 상태·사유 문구(M17), prefill 제거(m12).

### 4.4 Redesign이 수정할 파일 (삭제 없음)
- 전역: `src/app/globals.css`, `src/app/layout.tsx`
- Shell·공용: `src/components/admin-shell.tsx`, `src/components/app-error-panel.tsx`, `src/components/copy-button.tsx`, `src/components/help-tip.tsx`, `src/components/detail-list.tsx`, `src/components/json-viewer.tsx`, `src/components/status-badge.tsx`, `src/components/feature-state-badges.tsx`, `src/components/empty-state.tsx`, `src/components/filter-bar.tsx`, `src/components/pagination-bar.tsx`, `src/components/confirm-dialog.tsx`, `src/components/login-form.tsx`
- ui primitives: `src/components/ui/button-variants.ts`, `input.tsx`, `textarea.tsx`, `native-select.tsx`, `badge.tsx`, `checkbox.tsx`, `tabs.tsx`, `card.tsx`, `table.tsx`, `alert.tsx`, `field.tsx`, `dialog.tsx`, `alert-dialog.tsx`, `popover.tsx`, `tooltip.tsx`, `breadcrumb.tsx`, `data-table.tsx`, `skeleton.tsx`, `sonner.tsx`, `form-field-input.tsx`, `form-select.tsx`, `form-textarea.tsx`
- 페이지(features 계열): `src/app/home-client.tsx`, `src/app/features/features-client.tsx`, `src/app/features/[featureId]/feature-detail-page-client.tsx`, `src/app/curated-features/curated-feature-map-client.tsx`, `src/app/admin/features/admin-features-client.tsx`, `src/app/admin/features/feature-form-sections.tsx`, `src/app/admin/features/new/feature-create-client.tsx`, `src/app/admin/features/curated/curation-collections-client.tsx`, `src/app/admin/features/curated/curation-quarantine-panel.tsx`, `src/app/admin/curated-features/curated-features-client.tsx`, `src/app/admin/curated-features/[curatedFeatureId]/curated-feature-detail-client.tsx`, `src/app/admin/curated-features/curated-lifecycle.tsx`
- 페이지(admin 계열): `src/app/admin/dedup-reviews/dedup-review-client.tsx`, `src/app/admin/enrichment-reviews/enrichment-review-client.tsx`, `src/app/admin/issues/admin-issues-client.tsx`, `src/app/admin/offline-uploads/offline-uploads-client.tsx`, `src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx`, `src/app/admin/settings/settings-client.tsx`, `src/app/admin/files/files-client.tsx`, `src/app/admin/backups/backups-client.tsx`, `src/app/admin/curations/candidates/curation-candidates-client.tsx`
- 페이지(ops 계열): `src/app/ops/logs/logs-client.tsx`, `src/app/ops/consistency/consistency-client.tsx`, `src/app/ops/datasets/datasets-client.tsx`, `src/app/ops/cache-target-streams/cache-target-streams-client.tsx`, `src/app/ops/pipeline/pipeline-client.tsx`, `src/app/ops/pipeline/page.tsx`, `src/app/ops/pipeline/execution-timeline.tsx`, `src/app/ops/pipeline/events-panel.tsx`, `src/app/ops/pipeline/execution-detail-panel.tsx`, `src/app/ops/pipeline/schedule-panel.tsx`, `src/app/ops/pipeline/request-dialog.tsx`; 공용 util `src/lib/format.ts`(`formatCount` `—`, `shortId` `…` — M36/m2)
- 그 외: `<Link className={buttonVariants()}>` 사용 페이지 13개(M10 — base 클래스 수정 후 대부분 무변경, 검증만); 기존 statusLabel/label 사전 모듈(M20/M28 tone table 추가)
- 신규(선택): `SelectableRow` primitive(m7), `StatStrip`/`LiveBadge`(M37/M25), `LevelBadge`/`SeverityBadge`/`HttpStatusBadge`(M20), `ReviewCompareDialog`/`ScoreMetricStrip`/`ReviewFilterBar`(M42), ThemeProvider 마운트 파일(M16에서 dark 유지 선택 시), `design.md`(redesign 산출)

---
3 critical · 43 major · 12 minor
