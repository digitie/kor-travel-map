# 2026-11-11 Common UI 검토

이 목록은 구현 전 검색 결과다. 현재 이관 결과와 잔여 gate는 [통합 기록](common-unification-20261111.md)을 참조한다.


## 표 초기 조사

```text
packages/kor-travel-map-admin/frontend/e2e/home-nav.spec.ts:778:    // pipeline executions 테이블은 즉시 resolve되므로 DataTable skeleton과
packages/kor-travel-map-admin/frontend/e2e/c7-redacted-reporter.ts:152:        "<table><thead><tr><th>#</th><th>spec</th><th>status</th><th>duration_ms</th></tr></thead>" +
packages/kor-travel-map-admin/frontend/e2e/consistency-drilldown.spec.ts:280:    // 이 페이지는 row-click 상세 pane이 없다(DataTable에 onRowClick 미전달, source 확인).
packages/kor-travel-map-admin/frontend/e2e/consistency-drilldown.spec.ts:384:  test("empty state shows DataTable emptyMessage and zero count badge", async ({
packages/kor-travel-map-admin/frontend/e2e/consistency-drilldown.spec.ts:417:    // DataTable default emptyMessage(컴포넌트가 명시 전달) — 두 표 모두에 등장.
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:1124:    // '테이블' 탭 → DataTable이 emptyMessage='표시할 feature가 없습니다.' 렌더.
packages/kor-travel-map-admin/frontend/e2e/poi-cache-targets-edge.spec.ts:263:    // Targets와 Nearby 두 DataTable이 동일 emptyMessage를 쓴다(line 399 & 428) →
packages/kor-travel-map-admin/frontend/e2e/offline-uploads-edge.spec.ts:392:    // 이슈 DataTable: 각 이슈는 semantic <tr role=row>로 렌더되고(non-virtual
packages/kor-travel-map-admin/frontend/e2e/offline-uploads-edge.spec.ts:393:    // DataTable → shadcn Table primitive) row 접근성 이름은 셀 텍스트 concat이라
packages/kor-travel-map-admin/frontend/e2e/live/admin-issues-actions-write.live.spec.ts:201:  // DataTable emptyMessage 또는 table 랜드마크 중 하나만 보이면 통과.
packages/kor-travel-map-admin/frontend/src/components/section-card.tsx:33: * 요약 dl은 DetailList, 선택 목록은 SelectableRow, 표는 DataTable(Card 안에서는 자동 flush).
packages/kor-travel-map-admin/frontend/e2e/live/ops-consistency-drilldown-roundtrip.live.spec.ts:8:// status NativeSelect 하나뿐이고, DataTable에 onRowClick이 전달되지 않으며
packages/kor-travel-map-admin/frontend/src/components/empty-state.tsx:24: * 아이콘-위-제목 타일을 쓰지 않는다(M17). DataTable은 `emptyState` prop으로 같은 컴포넌트를
packages/kor-travel-map-admin/frontend/e2e/live/features-input-roundtrip.live.spec.ts:34://   table container       getByRole("table")  (DataTable)
packages/kor-travel-map-admin/frontend/e2e/live/features-input-roundtrip.live.spec.ts:154:/** DataTable renders a header <tr> (row 0) then body rows; row index 1 is the first data row. */
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:39:  DataTable,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:40:  DataTableClampCell,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:41:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:260:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:324:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:364:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:434:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:439:              <DataTableClampCell className="font-medium" lines={2}>
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:441:              </DataTableClampCell>
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:481:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:526:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:531:              <DataTableClampCell lines={2}>{issue.message}</DataTableClampCell>
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:554:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:604:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:626:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:658:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:692:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:705:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:774:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:808:        <DataTable
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:1264:          <DataTable
packages/kor-travel-map-admin/frontend/e2e/live/features-list.live.spec.ts:22://   table container       getByRole("table") (DataTable)
packages/kor-travel-map-admin/frontend/e2e/live/reviews.live.spec.ts:19:// AdminShell nav <Link> label, DataTable emptyMessage). status-select aria-label
packages/kor-travel-map-admin/frontend/e2e/live/reviews.live.spec.ts:68:// visible. The body is loose — either the DataTable empty message or the table
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:6:import { DataTable } from "./data-table";
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:36:describe("DataTable", () => {
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:38:    render(<DataTable columns={columns} data={data} getRowId={getRowId} />);
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:52:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:73:    render(<DataTable columns={columns} data={data} getRowId={getRowId} />);
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:82:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:94:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:108:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:121:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:146:    render(<DataTable columns={columns} data={data} getRowId={getRowId} />);
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.test.tsx:157:      <DataTable
packages/kor-travel-map-admin/frontend/src/components/feature-price-panel.tsx:19:  DataTable,
packages/kor-travel-map-admin/frontend/src/components/feature-price-panel.tsx:20:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-price-panel.tsx:299:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/components/feature-price-panel.tsx:445:            <DataTable
packages/kor-travel-map-admin/frontend/src/components/ui/table.tsx:32:      <table
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.tsx:6:export { VirtualTable as DataTable } from "@kor-travel/ui/virtual-table"
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.tsx:7:export type { DataTableProps, DataTableColumnMeta, DataTableEmptyState } from "@kor-travel/ui/virtual-table"
packages/kor-travel-map-admin/frontend/src/components/ui/data-table.tsx:9:export function DataTableClampCell({
packages/kor-travel-map-admin/frontend/src/app/ops/consistency/consistency-client.tsx:30:  DataTable,
packages/kor-travel-map-admin/frontend/src/app/ops/consistency/consistency-client.tsx:31:  DataTableClampCell,
packages/kor-travel-map-admin/frontend/src/app/ops/consistency/consistency-client.tsx:32:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/consistency/consistency-client.tsx:137:    meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/consistency/consistency-client.tsx:139:      <DataTableClampCell lines={2}>{row.original.message}</DataTableClampCell>
packages/kor-travel-map-admin/frontend/src/app/ops/consistency/consistency-client.tsx:277:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/consistency/consistency-client.tsx:314:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/home-client.tsx:37:  DataTable,
packages/kor-travel-map-admin/frontend/src/app/home-client.tsx:38:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/home-client.tsx:171:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/home-client.tsx:435:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/datasets/datasets-client.tsx:73:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/ops/datasets/datasets-client.tsx:1652:    meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/datasets/datasets-client.tsx:1781:        <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/datasets/datasets-client.tsx:1902:        <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/datasets/datasets-client.tsx:2597:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/datasets/datasets-client.tsx:2612:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/datasets/datasets-client.tsx:2800:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/cache-target-streams/cache-target-streams-client.tsx:28:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/ops/cache-target-streams/cache-target-streams-client.tsx:232:    meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/cache-target-streams/cache-target-streams-client.tsx:239:    meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/cache-target-streams/cache-target-streams-client.tsx:291:    meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/cache-target-streams/cache-target-streams-client.tsx:391:        <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/cache-target-streams/cache-target-streams-client.tsx:540:        <DataTable
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:38:  DataTable,
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:39:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:356:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:376:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:383:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:398:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:413:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:426:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:690:              <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:19:  DataTable,
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:20:  DataTableClampCell,
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:21:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:154:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:156:          <DataTableClampCell lines={2}>{row.original.message}</DataTableClampCell>
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:203:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:215:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:405:          <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/logs/logs-client.tsx:479:          <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/execution-timeline.tsx:21:import { DataTable } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/execution-timeline.tsx:768:      <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/files/files-client.tsx:45:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/files/files-client.tsx:525:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/files/files-client.tsx:790:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:55:  DataTable,
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:56:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:444:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:827:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/events-panel.tsx:24:  DataTable,
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/events-panel.tsx:25:  DataTableClampCell,
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/events-panel.tsx:26:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/events-panel.tsx:129:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/events-panel.tsx:162:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/events-panel.tsx:164:          <DataTableClampCell lines={2}>{row.original.message}</DataTableClampCell>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/events-panel.tsx:280:        <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:48:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:761:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:986:    <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:27:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:175:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:234:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:259:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:474:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/poi-cache-targets/poi-cache-targets-client.tsx:625:              <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:42:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:538:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:670:    <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/ops/geo-releases/geo-releases-client.tsx:39:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/ops/geo-releases/geo-releases-client.tsx:231:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/ops/geo-releases/geo-releases-client.tsx:236:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/ops/geo-releases/geo-releases-client.tsx:283:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/ops/geo-releases/geo-releases-client.tsx:439:          <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/ops/geo-releases/geo-releases-client.tsx:450:        <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/ops/geo-releases/geo-releases-client.tsx:577:              <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/settings/settings-client.tsx:28:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/settings/settings-client.tsx:68:    meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/settings/settings-client.tsx:155:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/settings/settings-client.tsx:298:          <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/settings/settings-client.tsx:318:          <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/offline-uploads/offline-uploads-client.tsx:47:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/offline-uploads/offline-uploads-client.tsx:336:    <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/offline-uploads/offline-uploads-client.tsx:365:    meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/offline-uploads/offline-uploads-client.tsx:388:    meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/offline-uploads/offline-uploads-client.tsx:591:          <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/offline-uploads/offline-uploads-client.tsx:848:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/offline-uploads/offline-uploads-client.tsx:1068:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/backups/backups-client.tsx:35:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/backups/backups-client.tsx:275:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/backups/backups-client.tsx:388:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/curations/candidates/curation-candidates-client.tsx:48:import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/curations/candidates/curation-candidates-client.tsx:333:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/curations/candidates/curation-candidates-client.tsx:348:      <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/issues/admin-issues-client.tsx:52:  DataTable,
packages/kor-travel-map-admin/frontend/src/app/admin/issues/admin-issues-client.tsx:53:  DataTableClampCell,
packages/kor-travel-map-admin/frontend/src/app/admin/issues/admin-issues-client.tsx:54:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/issues/admin-issues-client.tsx:690:        meta: { wrap: true } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/issues/admin-issues-client.tsx:695:              <DataTableClampCell lines={2}>{issue.message}</DataTableClampCell>
packages/kor-travel-map-admin/frontend/src/app/admin/issues/admin-issues-client.tsx:989:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/features/admin-features-client.tsx:62:import { DataTable } from "@/components/ui/data-table";
packages/kor-travel-map-admin/frontend/src/app/admin/features/admin-features-client.tsx:1076:            <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/features/new/feature-create-client.tsx:49:  DataTable,
packages/kor-travel-map-admin/frontend/src/app/admin/features/new/feature-create-client.tsx:50:  type DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/features/new/feature-create-client.tsx:630:        meta: { align: "right" } satisfies DataTableColumnMeta,
packages/kor-travel-map-admin/frontend/src/app/admin/features/new/feature-create-client.tsx:1121:          <DataTable
packages/kor-travel-map-admin/frontend/src/app/admin/features/curated/curation-collections-client.tsx:1009:                  <Table>
packages/kor-travel-map-admin/frontend/src/app/admin/features/curated/curation-collections-client.tsx:1424:      <Table>
packages/kor-travel-map-admin/frontend/src/app/admin/features/curated/curation-quarantine-panel.tsx:581:    <Table data-testid="quarantine-items-table">
```

## 오버레이 초기 조사

```text
packages/kor-travel-map-admin/frontend/src/components/help-tip.tsx:55:    <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
packages/kor-travel-map-admin/frontend/src/components/help-tip.tsx:56:      <TooltipProvider>
packages/kor-travel-map-admin/frontend/src/components/help-tip.tsx:57:        <Tooltip>
packages/kor-travel-map-admin/frontend/src/components/help-tip.tsx:58:          <TooltipTrigger
packages/kor-travel-map-admin/frontend/src/components/help-tip.tsx:59:            render={<PopoverTrigger render={trigger} />}
packages/kor-travel-map-admin/frontend/src/components/help-tip.tsx:61:          {popoverOpen ? null : <TooltipContent>{children}</TooltipContent>}
packages/kor-travel-map-admin/frontend/src/components/help-tip.tsx:64:      <PopoverContent align="start" className="leading-relaxed">
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:6:import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:23:  return <DialogPrimitive.Root data-slot="dialog" {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:27:  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:31:  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:51:    <DialogPrimitive.Portal>
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:52:      <DialogPrimitive.Backdrop
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:56:      <DialogPrimitive.Viewport
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:60:        <DialogPrimitive.Popup
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:92:    <DialogPrimitive.Title
packages/kor-travel-map-admin/frontend/src/components/ui/dialog.tsx:105:    <DialogPrimitive.Description
packages/kor-travel-map-admin/frontend/src/components/ui/button.tsx:2:import { Button as ButtonPrimitive } from "@base-ui/react/button"
packages/kor-travel-map-admin/frontend/src/components/ui/separator.tsx:4:import { Separator as SeparatorPrimitive } from "@base-ui/react/separator"
packages/kor-travel-map-admin/frontend/src/components/ui/input.tsx:3:import { Input as InputPrimitive } from "@base-ui/react/input"
packages/kor-travel-map-admin/frontend/src/components/ui/tabs.tsx:4:import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
packages/kor-travel-map-admin/frontend/src/components/ui/breadcrumb.tsx:3:import { mergeProps } from "@base-ui/react/merge-props"
packages/kor-travel-map-admin/frontend/src/components/ui/breadcrumb.tsx:4:import { useRender } from "@base-ui/react/use-render"
packages/kor-travel-map-admin/frontend/src/components/ui/alert-dialog.tsx:6:import { AlertDialog as AlertDialogPrimitive } from "@base-ui/react/alert-dialog"
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/schedule-panel.tsx:1053:<Dialog
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/schedule-panel.tsx:1061:        <DialogContent>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/schedule-panel.tsx:1062:          <DialogHeader>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/schedule-panel.tsx:1063:            <DialogTitle>스케줄 cron 수정</DialogTitle>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/schedule-panel.tsx:1064:            <DialogDescription>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/schedule-panel.tsx:1109:          <DialogFooter>
packages/kor-travel-map-admin/frontend/src/components/ui/tooltip.tsx:4:import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip"
packages/kor-travel-map-admin/frontend/src/components/ui/tooltip.tsx:19:    <TooltipPrimitive.Provider data-slot="tooltip-provider" delay={delay} {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/tooltip.tsx:24:  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/tooltip.tsx:28:  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/tooltip.tsx:44:    <TooltipPrimitive.Portal>
packages/kor-travel-map-admin/frontend/src/components/ui/tooltip.tsx:45:      <TooltipPrimitive.Positioner sideOffset={sideOffset} className="z-50">
packages/kor-travel-map-admin/frontend/src/components/ui/tooltip.tsx:46:        <TooltipPrimitive.Popup
packages/kor-travel-map-admin/frontend/src/components/ui/badge.tsx:2:import { mergeProps } from "@base-ui/react/merge-props"
packages/kor-travel-map-admin/frontend/src/components/ui/badge.tsx:3:import { useRender } from "@base-ui/react/use-render"
packages/kor-travel-map-admin/frontend/src/components/ui/popover.tsx:4:import { Popover as PopoverPrimitive } from "@base-ui/react/popover"
packages/kor-travel-map-admin/frontend/src/components/ui/popover.tsx:9:  return <PopoverPrimitive.Root data-slot="popover" {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/popover.tsx:13:  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/popover.tsx:37:    <PopoverPrimitive.Portal>
packages/kor-travel-map-admin/frontend/src/components/ui/popover.tsx:38:      <PopoverPrimitive.Positioner
packages/kor-travel-map-admin/frontend/src/components/ui/popover.tsx:43:        <PopoverPrimitive.Popup
packages/kor-travel-map-admin/frontend/src/components/ui/popover.tsx:61:  return <PopoverPrimitive.Close data-slot="popover-close" {...props} />
packages/kor-travel-map-admin/frontend/src/components/ui/checkbox.tsx:4:import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox"
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/request-dialog.tsx:1238:      <Dialog open={open} onOpenChange={handleOpenChange}>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/request-dialog.tsx:1239:        <DialogContent className="max-w-xl">
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/request-dialog.tsx:1240:          <DialogHeader>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/request-dialog.tsx:1241:            <DialogTitle>갱신 요청 생성</DialogTitle>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/request-dialog.tsx:1242:            <DialogDescription>
packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/request-dialog.tsx:1278:          <DialogFooter>
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:603:        <Popover>
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:604:          <PopoverTrigger render={<Button size="sm" variant="outline" />}>
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:608:          <PopoverContent align="end" className="w-auto" aria-label="Feature 상태 필터">
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:290:    <Dialog
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:296:      <DialogContent aria-label="dedup review detail" className="max-w-6xl">
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:297:        <DialogHeader>
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:299:            <DialogTitle>중복 상세 비교</DialogTitle>
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:300:            <DialogDescription>
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:252:    <Dialog
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:258:      <DialogContent
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:262:        <DialogHeader>
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:264:            <DialogTitle>보강 상세 비교</DialogTitle>
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:265:            <DialogDescription>
```

## 지도 초기 조사

```text
packages/map-marker-react/vite.config.ts:17:      external: ["react", "react-dom", "maplibre-gl"],
packages/map-marker-react/vite.config.ts:22:          "maplibre-gl": "maplibregl",
packages/map-marker-react/package.json:40:    "maplibre-gl": "6.17.0",
packages/map-marker-react/package.json:48:    "maplibre-gl": "6.17.0",
packages/map-marker-react/src/palette.ts:8: * 디버그 UI(maplibre marker)와 PinVi user UI에서 동일 매핑을 공유해
packages/map-marker-react/src/index.ts:6: * 자체는 maplibre/React에 종속되지 않는 **순수 DOM factory + lookup table** —
packages/map-marker-react/src/marker.ts:2: * `createMarkerElement` — maplibre `Marker`에 넘길 HTMLElement 팩토리.
packages/map-marker-react/src/marker.ts:4: * maplibre의 `new maplibregl.Marker({ element })`는 임의 DOM 요소를 받으므로,
packages/map-marker-react/src/marker.ts:20:  /** `:hover`/`:click` 처리. maplibre marker는 내부에서 popup 등 다른 layer를 띄울 때
packages/map-marker-react/src/marker.ts:30: * maplibre.Marker용 HTMLElement 생성. 동그란 색상 배지에 maki 글리프(또는 첫
packages/map-marker-react/src/marker.ts:34: *     new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map);
packages/kor-travel-map-admin/frontend/package.json:7:    "predev": "node ./scripts/copy-maplibre-worker.mjs",
packages/kor-travel-map-admin/frontend/package.json:9:    "prebuild": "node ./scripts/copy-maplibre-worker.mjs",
packages/kor-travel-map-admin/frontend/package.json:37:    "maplibre-gl": "6.17.0",
packages/kor-travel-map-admin/frontend/e2e/map-control-assertions.ts:8:  const scale = page.locator(".maplibregl-ctrl-scale");
packages/kor-travel-map-admin/frontend/e2e/features-new-submit.spec.ts:24: * NOTE: Playwright는 Windows 호스트에서만 실행된다. 지도(maplibre)는 VWorld key 없이
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:101:            | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:103:          return Boolean(container?._maplibreMap);
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:112:      ) as (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map }) | null;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:113:      container?._maplibreMap?.jumpTo({
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:126:    ) as (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map }) | null;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:127:    return container?._maplibreMap?.getZoom() ?? Number.NaN;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:132: * maplibre canvas(tabindex=0)에서 Tab을 한 번 누른다. DOM 마커는 같은 canvas container의
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:136:  const canvas = page.locator("canvas.maplibregl-canvas");
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:522:            | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:524:          const map = container?._maplibreMap;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:538:                _maplibreMap?: import("maplibre-gl").Map;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:541:          return container?._maplibreMap?.querySourceFeatures(id).length ?? 0;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:558:                _maplibreMap?: import("maplibre-gl").Map;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:561:          const map = container?._maplibreMap;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:570:      ) as (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map }) | null;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:571:      if (!container?._maplibreMap)
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:572:        throw new Error("maplibre map is not ready");
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:573:      const map = container._maplibreMap;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:624:        fireSourceData("vworld-raster-test", true);
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:635:          container.querySelectorAll('.maplibregl-marker [aria-hidden="true"]'),
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:646:          '.maplibregl-marker[role="button"]',
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:655:          '.maplibregl-marker[role="button"]',
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:755:            | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:757:          const map = container?._maplibreMap;
packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts:760:            | import("maplibre-gl").GeoJSONSource
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:73:        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:75:      return container?._maplibreMap !== undefined;
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:84:        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:86:      const current = container?._maplibreMap?.getCenter();
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:96:        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:98:      container?._maplibreMap?.jumpTo({ center: [lon, lat], zoom });
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:142:      "/maplibre/maplibre-gl-worker.mjs",
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:143:      "/maplibre/maplibre-gl-shared.mjs",
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:575: *  - maplibre 캔버스가 blank가 아님(스크린샷 색 분산 휴리스틱, 관대한 임계치)
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:576: *  - 적어도 1개의 `.maplibregl-marker`(feature 점 또는 클러스터)가 존재
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:583:const CANVAS_SELECTOR = ".maplibregl-canvas";
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:584:const MARKER_SELECTOR = ".maplibregl-marker";
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:585:const CLUSTER_SELECTOR = '.maplibregl-marker[aria-label^="feature 클러스터"]';
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:629:    // maplibre 캔버스가 부착되고 크기가 잡힐 때까지 대기.
packages/kor-travel-map-admin/frontend/e2e/live/features-map.live.spec.ts:644:  test("적어도 1개의 maplibre 마커(점/클러스터)가 렌더됨", async ({ page }) => {
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:37: *   - 지도 인스턴스 e2e 훅: components/vworld-map-view.tsx (`container._maplibreMap`).
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:65:  '.maplibregl-marker[role="button"]:not([aria-label^="feature 클러스터"])';
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:67:  '.maplibregl-marker[role="button"][aria-label^="feature 클러스터"]';
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:238:// ── 지도 인스턴스 제어/판독(컨테이너 DOM에 매달린 _maplibreMap 훅) ──────────
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:249:        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:251:      container?._maplibreMap?.jumpTo({ center: [lon, lat], zoom });
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:262:        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:264:      const map = container?._maplibreMap;
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:352:        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:354:      const map = container?._maplibreMap;
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:491:  const rows = page.locator(".maplibregl-popup button");
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:513:        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:515:      const map = container?._maplibreMap;
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:566:    .locator(".maplibregl-popup button:not(.maplibregl-popup-close-button)")
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:579:      | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
packages/kor-travel-map-admin/frontend/e2e/live/features-map-input-roundtrip.live.spec.ts:581:    const map = container?._maplibreMap;
packages/kor-travel-map-admin/frontend/e2e/live/reviews-decide-write.live.spec.ts:839:        dataset_key: "vworld",
packages/kor-travel-map-admin/frontend/e2e/live/reviews-decide-write.live.spec.ts:841:      await page.getByLabel("dedup dataset").fill("vworld");
packages/kor-travel-map-admin/frontend/src/components/feature-detail-view.tsx:46:import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:8:// maplibre-gl 6은 default export를 없앴다(보안 권고 GHSA-jrc7-96c5-q579 대응으로
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:9:// 5.x에서 올라왔다). 이 파일은 `maplibregl`을 값(`new maplibregl.Marker`)과
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:10:// 타입 네임스페이스(`maplibregl.GeoJSONSource`) 양쪽으로 쓰므로 namespace
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:13:import * as maplibregl from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:18:} from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:40:} from "@/lib/vworld-style";
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:46://: 내보내지 않는다. maplibre 6의 worker(`maplibre-gl-worker.mjs`)는
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:47://: `maplibre-gl-shared.mjs`를 상대 경로로 import하는데, 기본 경로인 blob URL
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:58://: 파일은 `scripts/copy-maplibre-worker.mjs`가 `predev`/`prebuild`에서
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:59://: `public/maplibre/`로 복사한다(상류 문서의 Turbopack 절). 이 호출은 지도를
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:61://: `new maplibregl.Map`을 부르는 **유일한** 자리다.
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:62:maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:91:  onClick?: (event: maplibregl.MapMouseEvent) => void;
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:92:  onContextMenu?: (event: maplibregl.MapMouseEvent) => void;
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:94:    lngLat: maplibregl.LngLat;
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:99:  onError?: (event: maplibregl.ErrorEvent) => void;
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:157:    const nextMap = new maplibregl.Map({
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:180:      | (HTMLDivElement & { _maplibreMap?: MapLibreMap })
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:182:    if (containerNode) containerNode._maplibreMap = nextMap;
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:198:    const handleClick = (event: maplibregl.MapMouseEvent) => {
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:201:    const handleContextMenu = (event: maplibregl.MapMouseEvent) => {
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:204:    const handleError = (event: maplibregl.ErrorEvent) => {
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:300:    const controls: Array<maplibregl.IControl> = [];
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:302:      const control = new maplibregl.NavigationControl({
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:309:      const control = new maplibregl.ScaleControl({
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:340:      if (containerNode) delete containerNode._maplibreMap;
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:488:    const marker = new maplibregl.Marker({ element })
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:745:  // maplibre 기본 center 앵커가 wrapper 중앙(=아이콘과 라벨 사이)을 좌표에 놓아, 아이콘이
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:914:  const handleGeometryClick = (event: maplibregl.MapLayerMouseEvent) => {
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1031:  const marker = new maplibregl.Marker({ element, anchor: "center" })
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1045: * maplibre `cluster:true`(개별 feature 재군집)를 쓰지 않으므로 count가 서버 집계 그대로다.
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1111: * maplibre 네이티브 클러스터링(GeoJSON source `cluster:true`)으로 feature 점을
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1113: * (maplibre 공식 "Display HTML clusters" 패턴). VWorld style에 sprite/glyphs가
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1250:      | maplibregl.GeoJSONSource
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1260:      | maplibregl.GeoJSONSource
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1292:        marker = new maplibregl.Marker({ anchor: "center", element })
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1473:      popupRef.current = new maplibregl.Popup({
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1484:      source: maplibregl.GeoJSONSource,
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1586:              const source = map.getSource(SRC) as maplibregl.GeoJSONSource;
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1621:            marker = new maplibregl.Marker({ element }).setLngLat(coords);
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1685:            marker = new maplibregl.Marker({ element }).setLngLat(coords);
packages/kor-travel-map-admin/frontend/src/components/vworld-map-view.tsx:1730:    const handleSourceData = (event: maplibregl.MapSourceDataEvent) => {
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:9: * maplibre worker 배선이 **실제로 성립하는지** 센다.
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:14: * 것이다 — worker(`maplibre-gl-worker.mjs`)가 `maplibre-gl-shared.mjs`를 상대
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:23:const SCRIPT = path.join(FRONTEND_ROOT, "scripts", "copy-maplibre-worker.mjs");
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:24:const MAP_VIEW = path.join(FRONTEND_ROOT, "src", "components", "vworld-map-view.tsx");
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:37:  if (match === null) throw new Error("vworld-map-view.tsx가 setWorkerUrl을 부르지 않는다");
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:41:describe("maplibre worker 배선", () => {
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:45:    expect(files).toContain("maplibre-gl-worker.mjs");
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:46:    expect(files).toContain("maplibre-gl-shared.mjs");
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:51:    expect(url.startsWith("/maplibre/")).toBe(true);
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:60:      expect(pkg.scripts[hook] ?? "").toContain("copy-maplibre-worker.mjs");
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:65:    // 선언이 아니라 **효과**를 센다 — 설치된 maplibre가 그 파일들을 더 이상 내보내지
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:67:    const workdir = mkdtempSync(path.join(tmpdir(), "maplibre-worker-"));
packages/kor-travel-map-admin/frontend/src/components/maplibre-worker-wiring.test.ts:70:      expect(existsSync(path.join(workdir, "public", "maplibre", file))).toBe(true);
packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts:1:import type { StyleSpecification } from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts:3:// `digitie/maplibre-vworld-react` a7cb0f8의 vworld-map-core/web 경계를
packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts:61:function vworldLayerName(mapType: VWorldMapType): string {
packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts:83:  const layerName = vworldLayerName(mapType);
packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts:84:  return `https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(
packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts:130:      "vworld-satellite",
packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts:131:      "vworld-satellite-layer",
packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts:135:  appendRasterLayer("vworld-base", "vworld-base-layer", layerType);
packages/kor-travel-map-admin/frontend/src/app/map-ui-has-no-weather.test.ts:133:    expect(files.some((f) => f.endsWith(path.join("components", "vworld-map-view.tsx")))).toBe(
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:4:import type { LngLatBounds, Map as MapLibreMap } from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:5:import "maplibre-gl/dist/maplibre-gl.css";
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:66:} from "@/components/vworld-map-view";
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:69:import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx:158:      : panelRef.current?.closest(".kt-map-stage")?.querySelector<HTMLElement>(".maplibregl-canvas");
packages/kor-travel-map-admin/frontend/src/app/features/feature-detail-focus.test.tsx:7:vi.mock("@/components/vworld-map-view", () => ({}));
packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.test.ts:16:    vi.stubEnv("NEXT_PUBLIC_VWORLD_API_KEY", "vworld-provider-key");
packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.test.ts:59:    vi.stubEnv("NEXT_PUBLIC_VWORLD_API_KEY", "vworld-provider-key");
packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.test.ts:77:    expect(headers.get("X-KTG-API-Key")).not.toBe("vworld-provider-key");
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:10:import { type Map as MapLibreMap } from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/app/admin/dedup-reviews/dedup-review-client.tsx:60:import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:6:import { type Map as MapLibreMap } from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/app/admin/enrichment-reviews/enrichment-review-client.tsx:54:import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
packages/kor-travel-map-admin/frontend/src/app/admin/features/admin-features-client.tsx:67:import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
packages/kor-travel-map-admin/frontend/src/app/admin/features/feature-form-sections.tsx:4:import type { Map as MapLibreMap } from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/app/admin/features/feature-form-sections.tsx:15:import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
packages/kor-travel-map-admin/frontend/src/app/admin/features/feature-form-sections.tsx:35:import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:4:import type { LngLatBounds, Map as MapLibreMap } from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:5:import "maplibre-gl/dist/maplibre-gl.css";
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:49:} from "@/components/vworld-map-view";
packages/kor-travel-map-admin/frontend/src/app/curated-features/curated-feature-map-client.tsx:52:import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
packages/kor-travel-map-admin/frontend/src/app/admin/features/new/feature-create-client.tsx:5:import type { Map as MapLibreMap } from "maplibre-gl";
packages/kor-travel-map-admin/frontend/src/app/admin/features/new/feature-create-client.tsx:6:import "maplibre-gl/dist/maplibre-gl.css";
```
