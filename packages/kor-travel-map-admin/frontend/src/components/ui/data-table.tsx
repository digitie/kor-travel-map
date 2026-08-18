"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

// 공용 headless DataTable — @tanstack/react-table v8(STABLE) 기반. admin/ops UI의 모든
// 테이블이 본 컴포넌트로 통일된다(ADR/마이그레이션 2026-06-17). 기본은 semantic
// shadcn Table primitive로 렌더해 접근성(role=table/columnheader/row/cell)과 기존
// Playwright 셀렉터를 보존하고, 대용량/무한 목록만 `virtualized`로 @tanstack/react-virtual
// 윈도잉을 켠다(이때는 display:grid라 native table role이 죽으므로 role=table/rowgroup/row/
// columnheader/cell을 명시하고 aria-rowcount/aria-rowindex를 얹는다).
//
// 데이터 연산은 기본 server-side(manualSorting 기본 true): 페이지의 react-query가 이미
// cursor 페이징/필터/정렬을 수행하므로 DataTable은 data만 받아 렌더한다(서버 정렬이
// 일반적 케이스라 #502에서 기본을 manual로 뒤집었다). 전체 데이터셋을 한 번에 보유하는
// 완전 client 목록만 manualSorting={false}로 getSortedRowModel을 켠다.
//
// 상태 표면(design.md): loading = 형태가 맞는 skeleton 행(`aria-busy`), empty = 좌측 정렬
// EmptyState(제목 + 이유 + 행동 1개, `emptyState`), error = what/why/what-to-do Alert +
// `다시 시도`(`onRetry`). 숫자 column은 `meta.align: "right"`(tabular-nums는 Table 기본),
// 긴 본문 column은 `meta.wrap: true`로 clamp/wrap을 허용한다.

import * as React from "react"
import {
  type Cell,
  type Column,
  type ColumnDef,
  type Header,
  type OnChangeFn,
  type Row,
  type RowSelectionState,
  type SortingState,
  type Table as TanstackTable,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { useVirtualizer } from "@tanstack/react-virtual"
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react"

import { EmptyState } from "@/components/empty-state"
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

/**
 * ColumnDef.meta에 넣는 표시 힌트. 예:
 *   { accessorKey: "duration_ms", header: "소요", meta: { align: "right" } satisfies DataTableColumnMeta }
 */
export interface DataTableColumnMeta {
  /** 정렬 — 숫자/시각/크기 column은 "right"(우측 정렬, M24). */
  align?: "left" | "center" | "right"
  /** 긴 본문(message 등) — whitespace-normal로 wrap/line-clamp 허용(M38). */
  wrap?: boolean
  /** th·td 공통 className. */
  className?: string
  /** th 전용 className. */
  headerClassName?: string
  /** td 전용 className. */
  cellClassName?: string
}

/** 비었을 때 표시할 내용 — 무엇이 비었나 · 왜/다음 행동 · 행동 1개. */
export interface DataTableEmptyState {
  title: string
  description?: React.ReactNode
  action?: React.ReactNode
  icon?: React.ReactNode
}

export interface DataTableProps<TData> {
  columns: ColumnDef<TData, unknown>[]
  data: TData[]
  /** row.id를 도메인 안정 id로 고정(권장) — 정렬/선택/가상화 키 안정성. */
  getRowId?: (row: TData, index: number) => string
  /** react-query 상태를 그대로 넘기면 skeleton/alert/empty를 내부에서 렌더. */
  isLoading?: boolean
  isError?: boolean
  error?: { message?: string } | null
  /** 오류 제목(what). 기본 `목록을 불러오지 못했습니다`. */
  errorTitle?: string
  /** 오류 슬롯 전체를 대체(페이지가 AppErrorPanel 등을 직접 렌더할 때). */
  errorState?: React.ReactNode
  /** 오류 시 `다시 시도` 버튼에 연결할 refetch. Promise를 돌려주면(예: `() => query.refetch()`)
   *  resolve될 때까지 버튼을 loading 상태로 잠근다 — 페이지가 진행 상태를 따로 넘기지 않는다. */
  onRetry?: () => void | Promise<unknown>
  /** 비었을 때 colSpan 행에 표시할 문구(제목만). `emptyState`가 있으면 그것이 우선. */
  emptyMessage?: string
  /** 비었을 때 표시할 EmptyState(제목 + 이유 + 행동 1개). */
  emptyState?: DataTableEmptyState
  /** skeleton 행 수(기본 6). 예상 페이지 크기에 맞추면 layout shift가 줄어든다. */
  skeletonRowCount?: number
  /** 정렬: 제어(서버) 모드면 sorting+onSortingChange 전달 + manualSorting. */
  sorting?: SortingState
  onSortingChange?: OnChangeFn<SortingState>
  /** true면 getSortedRowModel을 켜지 않음(서버 정렬). 기본 true(서버 정렬).
   *  완전 client 목록(전체 데이터셋을 한 번에 보유)만 manualSorting={false}로
   *  getSortedRowModel을 켠다. cursor/page_size 목록은 서버가 정렬을 소유하므로
   *  기본값(true)을 그대로 두고, 서버가 정렬하지 않는 accessor는 enableSorting:false로. */
  manualSorting?: boolean
  /** 행 선택(opt-in) — 체크박스 컬럼 + 선택 상태. 함수를 주면 행별 선택 가능 여부
   *  (react-table getCanSelect) — 선택 불가 행은 체크박스 disabled + select-all 제외. */
  enableRowSelection?: boolean | ((row: Row<TData>) => boolean)
  rowSelection?: RowSelectionState
  onRowSelectionChange?: OnChangeFn<RowSelectionState>
  /** 행 체크박스의 이름 조각 — `${rowSelectionLabel(row)} 선택`으로 접근성 이름을 만든다.
   *  주지 않으면 모든 행이 같은 이름(`행 선택`)이라 스크린리더/셀렉터가 행을 구분하지 못한다.
   *  행을 식별하는 짧은 값(이름·id)을 주고, column 재생성을 막기 위해 module-level 함수나
   *  useCallback으로 안정화한다. */
  rowSelectionLabel?: (row: TData) => string
  /** 선택된 행이 있을 때 테이블 위에 표시할 bulk action 바. */
  renderBulkActions?: (rows: Row<TData>[]) => React.ReactNode
  /** 행 클릭(detail pane 선택 등). 내부 link/button은 stopPropagation 해야 함. */
  onRowClick?: (row: TData) => void
  /** 행 active(detail pane 강조) — data-state="selected". */
  isRowActive?: (row: TData) => boolean
  /** 행별 data-testid(e2e 셀렉터 등). 값을 주면 비가상 경로의 <tr data-testid>로 렌더. */
  rowTestId?: (row: TData) => string | undefined
  /** cursor 순서 검증용 불투명 행 identity. 비가상 경로의 <tr data-row-identity>로 렌더. */
  rowIdentity?: (row: TData) => string | undefined
  /** 가상화(대용량/무한 목록만). 켜면 display:grid 레이아웃 + 명시 role=table 계열 ARIA. */
  virtualized?: boolean
  estimateRowSize?: number
  overscan?: number
  /** 스크롤 컨테이너 className — Table 자신의 컨테이너(hairline 1층)에 합쳐진다: 높이 제한
   *  (`max-h-80`)·스크롤 축만 준다(테두리/배경/모서리를 다시 주지 않는다). 가상화 시 고정 높이 필수
   *  (예: h-[calc(100vh-16rem)]). */
  containerClassName?: string
  /** 테이블 caption(스크린리더용). */
  ariaLabel?: string
}

function columnMeta<TData>(column: Column<TData, unknown>): DataTableColumnMeta {
  return (column.columnDef.meta ?? {}) as DataTableColumnMeta
}

/**
 * 긴 본문 셀(로그 message·이벤트 payload 요약)의 표준 — column에 `meta: { wrap: true }`를 주고
 * cell을 이 컴포넌트로 감싸면 N줄로 clamp되고 말줄임이 보인다(M38). 잘린 전문은 hover title이
 * 아니라 행 상세(onRowClick → inspector rail)로 도달하게 한다 — title은 보조 신호일 뿐이다.
 */
export function DataTableClampCell({
  lines = 2,
  className,
  title,
  children,
}: {
  /** clamp 줄 수(1–3). */
  lines?: 1 | 2 | 3
  className?: string
  /** 전문(문자열이면 title로도 노출). */
  title?: string
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        "max-w-96 whitespace-normal break-words",
        lines === 1 && "line-clamp-1",
        lines === 2 && "line-clamp-2",
        lines === 3 && "line-clamp-3",
        className,
      )}
      title={title ?? (typeof children === "string" ? children : undefined)}
    >
      {children}
    </div>
  )
}

function alignClass(align: DataTableColumnMeta["align"]): string | undefined {
  if (align === "right") return "text-right"
  if (align === "center") return "text-center"
  return undefined
}

function flexAlignClass(align: DataTableColumnMeta["align"]): string | undefined {
  if (align === "right") return "justify-end text-right"
  if (align === "center") return "justify-center text-center"
  return undefined
}

/** 정렬 가능한 헤더 버튼 — 접근성 이름은 title 그대로 보존(글리프 aria-hidden), th에 aria-sort.
 *  th와 같은 12px/600 활자(정렬 버튼이 헤더 텍스트보다 커 보이지 않게, M3). */
function DataTableColumnHeader({
  title,
  sorted,
  canSort,
  align,
  onToggle,
}: {
  title: string
  sorted: false | "asc" | "desc"
  canSort: boolean
  align?: DataTableColumnMeta["align"]
  onToggle?: (event: React.MouseEvent) => void
}) {
  if (!canSort) return <>{title}</>
  const Glyph = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ChevronsUpDown
  return (
    <button
      type="button"
      data-sorted={sorted || undefined}
      className={cn(
        "inline-flex h-7 items-center gap-1 rounded-control px-2 text-2xs leading-none font-semibold whitespace-nowrap text-text-secondary transition-[color,background-color,border-color] select-none hover:bg-surface-muted hover:text-text-primary focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus active:translate-y-px data-[sorted]:text-text-primary",
        align === "right" ? "-mr-2 flex-row-reverse" : "-ml-2",
      )}
      onClick={onToggle}
    >
      {title}
      <Glyph
        className={cn("size-3.5 shrink-0", sorted ? "text-brand" : "text-text-tertiary")}
        aria-hidden="true"
      />
    </button>
  )
}

function ariaSort(sorted: false | "asc" | "desc"): "ascending" | "descending" | "none" {
  if (sorted === "asc") return "ascending"
  if (sorted === "desc") return "descending"
  return "none"
}

function renderHeadCellContent<TData>(
  header: Header<TData, unknown>,
  sorted: false | "asc" | "desc",
  canSort: boolean,
) {
  if (header.isPlaceholder) return null
  if (typeof header.column.columnDef.header === "string") {
    return (
      <DataTableColumnHeader
        title={header.column.columnDef.header}
        sorted={sorted}
        canSort={canSort}
        align={columnMeta(header.column).align}
        onToggle={header.column.getToggleSortingHandler()}
      />
    )
  }
  return flexRender(header.column.columnDef.header, header.getContext())
}

function handleClickableRowKeyDown<TData>(
  event: React.KeyboardEvent<HTMLTableRowElement>,
  row: TData,
  onRowClick: (row: TData) => void,
) {
  if (event.target !== event.currentTarget) return
  if (event.key !== "Enter" && event.key !== " ") return
  event.preventDefault()
  onRowClick(row)
}

/** 클릭 가능한 행의 focus 표면 — 표 안이라 inset outline(이웃 행/스크롤 컨테이너에 잘리지 않게)
 *  + 배경 변화(색 1채널이 아니게). 링은 즉시 나타나야 하므로(design.md §Focus) 행의 전환은
 *  `transition-colors`가 아니라 `transition-[color,background-color,border-color]`로 열거한다 —
 *  tailwind v4의 `transition-colors`는 `outline-color`를 포함해서 링 색이 100ms 페이드인 된다. */
const CLICKABLE_ROW_CLASS =
  "cursor-pointer focus-visible:bg-surface-subtle focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus active:bg-surface-muted"

/** 선택 열. 행 체크박스 이름은 `rowSelectionLabel`이 있으면 행마다 다르게(`홍길동 선택`),
 *  없으면 기존 계약대로 `행 선택`으로 남는다(호출부 호환). */
function selectionColumn<TData>(
  rowSelectionLabel?: (row: TData) => string,
): ColumnDef<TData, unknown> {
  return {
    id: "__select__",
    enableSorting: false,
    size: 36,
    header: ({ table }) => (
      <Checkbox
        aria-label="전체 선택"
        checked={table.getIsAllPageRowsSelected()}
        indeterminate={table.getIsSomePageRowsSelected()}
        onCheckedChange={(checked) => table.toggleAllPageRowsSelected(!!checked)}
      />
    ),
    cell: ({ row }) => (
      <Checkbox
        aria-label={
          rowSelectionLabel ? `${rowSelectionLabel(row.original)} 선택` : "행 선택"
        }
        checked={row.getIsSelected()}
        disabled={!row.getCanSelect()}
        onCheckedChange={(checked) => row.toggleSelected(!!checked)}
        onClick={(event) => event.stopPropagation()}
      />
    ),
  }
}

const DEFAULT_ERROR_TITLE = "목록을 불러오지 못했습니다"
const DEFAULT_ERROR_WHY = "서버가 응답하지 않았거나 요청이 거부되었습니다."
const DEFAULT_ERROR_NEXT = "잠시 후 다시 시도하세요."

function DataTableError({
  title,
  message,
  onRetry,
}: {
  title: string
  message: string | undefined
  onRetry?: () => void | Promise<unknown>
}) {
  // 재시도 진행 상태는 onRetry가 돌려준 Promise로 스스로 판단한다(페이지 prop 없음).
  // React 19는 unmount 후 setState를 무시하므로 mounted guard가 필요 없다.
  const [retrying, setRetrying] = React.useState(false)
  const handleRetry = () => {
    if (!onRetry) return
    const result: unknown = onRetry()
    if (!(result instanceof Promise)) return
    setRetrying(true)
    void result.catch(() => undefined).finally(() => setRetrying(false))
  }
  return (
    <Alert variant="destructive">
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <span>{message ?? DEFAULT_ERROR_WHY}</span>
        {onRetry ? null : <span className="ml-1">{DEFAULT_ERROR_NEXT}</span>}
      </AlertDescription>
      {onRetry ? (
        <AlertActions>
          <Button
            loading={retrying}
            size="sm"
            type="button"
            variant="outline"
            onClick={handleRetry}
          >
            다시 시도
          </Button>
        </AlertActions>
      ) : null}
    </Alert>
  )
}

export function DataTable<TData>({
  columns,
  data,
  getRowId,
  isLoading,
  isError,
  error,
  errorTitle = DEFAULT_ERROR_TITLE,
  errorState,
  onRetry,
  emptyMessage = "데이터가 없습니다.",
  emptyState,
  skeletonRowCount = 6,
  sorting,
  onSortingChange,
  manualSorting = true,
  enableRowSelection = false,
  rowSelection,
  onRowSelectionChange,
  rowSelectionLabel,
  renderBulkActions,
  onRowClick,
  isRowActive,
  rowTestId,
  rowIdentity,
  virtualized = false,
  estimateRowSize = 40,
  overscan = 12,
  containerClassName,
  ariaLabel,
}: DataTableProps<TData>) {
  "use no memo"

  const [internalSorting, setInternalSorting] = React.useState<SortingState>([])
  const [internalSelection, setInternalSelection] = React.useState<RowSelectionState>({})

  const resolvedColumns = React.useMemo(
    () =>
      enableRowSelection
        ? [selectionColumn<TData>(rowSelectionLabel), ...columns]
        : columns,
    [columns, enableRowSelection, rowSelectionLabel],
  )

  // TanStack Table은 함수형 객체를 반환하므로 이 컴포넌트는 React Compiler 대상이 아니다.
  const table = useReactTable({
    data,
    columns: resolvedColumns,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: manualSorting ? undefined : getSortedRowModel(),
    manualSorting,
    enableRowSelection,
    state: {
      sorting: sorting ?? internalSorting,
      ...(enableRowSelection ? { rowSelection: rowSelection ?? internalSelection } : {}),
    },
    onSortingChange: onSortingChange ?? setInternalSorting,
    onRowSelectionChange: onRowSelectionChange ?? setInternalSelection,
  })

  if (isError) {
    if (errorState !== undefined) return <>{errorState}</>
    return (
      <DataTableError
        title={errorTitle}
        message={error?.message}
        onRetry={onRetry}
      />
    )
  }

  const rows = table.getRowModel().rows
  const colCount = table.getAllLeafColumns().length
  const selectedRows = enableRowSelection ? table.getSelectedRowModel().rows : []
  const resolvedEmpty: DataTableEmptyState = emptyState ?? { title: emptyMessage }

  const bulkBar =
    enableRowSelection && renderBulkActions && selectedRows.length > 0 ? (
      <div
        className="flex flex-wrap items-center gap-2 rounded-control bg-brand-tint px-3 py-2 text-xs text-text-primary"
        data-slot="bulk-actions"
        role="region"
        aria-label="선택 항목 작업"
      >
        <span className="font-medium tabular-nums">{selectedRows.length}개 선택됨</span>
        {renderBulkActions(selectedRows)}
      </div>
    ) : null

  return (
    <div className="space-y-2">
      {bulkBar}
      {virtualized ? (
        <VirtualizedTable
          table={table}
          rows={rows}
          colCount={colCount}
          isLoading={isLoading}
          emptyState={resolvedEmpty}
          skeletonRowCount={skeletonRowCount}
          estimateRowSize={estimateRowSize}
          overscan={overscan}
          onRowClick={onRowClick}
          isRowActive={isRowActive}
          containerClassName={containerClassName}
          ariaLabel={ariaLabel}
        />
      ) : (
        <Table
          aria-busy={isLoading || undefined}
          aria-label={ariaLabel}
          containerClassName={containerClassName}
        >
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sorted = header.column.getIsSorted()
                  const canSort = header.column.getCanSort()
                  const meta = columnMeta(header.column)
                  return (
                    <TableHead
                      aria-sort={canSort ? ariaSort(sorted) : undefined}
                      className={cn(alignClass(meta.align), meta.className, meta.headerClassName)}
                      key={header.id}
                    >
                      {renderHeadCellContent(header, sorted, canSort)}
                    </TableHead>
                  )
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <SkeletonRows columns={table.getAllLeafColumns()} rowCount={skeletonRowCount} />
            ) : rows.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={colCount} className="px-3 py-0 whitespace-normal">
                  <EmptyState
                    action={resolvedEmpty.action}
                    description={resolvedEmpty.description}
                    icon={resolvedEmpty.icon}
                    size="sm"
                    title={resolvedEmpty.title}
                  />
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => {
                const active = row.getIsSelected() || isRowActive?.(row.original) === true
                return (
                  <TableRow
                    key={row.id}
                    data-row-identity={rowIdentity?.(row.original)}
                    data-testid={rowTestId?.(row.original)}
                    data-state={active ? "selected" : undefined}
                    aria-selected={onRowClick ? active : undefined}
                    className={onRowClick ? CLICKABLE_ROW_CLASS : undefined}
                    tabIndex={onRowClick ? 0 : undefined}
                    onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                    onKeyDown={
                      onRowClick
                        ? (event) => handleClickableRowKeyDown(event, row.original, onRowClick)
                        : undefined
                    }
                  >
                    {row.getVisibleCells().map((cell) => {
                      const meta = columnMeta(cell.column)
                      return (
                        <TableCell
                          key={cell.id}
                          className={cn(
                            alignClass(meta.align),
                            meta.wrap && "whitespace-normal",
                            meta.className,
                            meta.cellClassName,
                          )}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

// skeleton 행 — 실제 행과 같은 셀 구조, 폭은 column마다 조금씩 다르게(형태가 맞는 skeleton).
const SKELETON_WIDTHS = ["w-3/4", "w-1/2", "w-2/3", "w-2/5", "w-3/5", "w-1/3"] as const

function skeletonWidth(rowIndex: number, columnIndex: number): string {
  return SKELETON_WIDTHS[(rowIndex + columnIndex) % SKELETON_WIDTHS.length]
}

function SkeletonRows<TData>({
  columns,
  rowCount,
}: {
  columns: Column<TData, unknown>[]
  rowCount: number
}) {
  const rowKeys = Array.from({ length: Math.max(1, rowCount) }, (_, index) => `skeleton-row-${index + 1}`)
  return (
    <>
      {rowKeys.map((rowKey, rowIndex) => (
        <TableRow className="hover:bg-transparent" key={rowKey}>
          {columns.map((column, columnIndex) => {
            const meta = columnMeta(column)
            return (
              <TableCell
                className={cn(alignClass(meta.align), meta.className, meta.cellClassName)}
                key={`${rowKey}-${column.id}`}
              >
                <Skeleton
                  className={cn(
                    "h-4",
                    skeletonWidth(rowIndex, columnIndex),
                    meta.align === "right" && "ml-auto",
                  )}
                />
              </TableCell>
            )
          })}
        </TableRow>
      ))}
    </>
  )
}

// 가상화 변형 — display:grid + sticky thead + absolute rows. display가 table-*가 아니면
// 브라우저가 table/row/columnheader/cell 암묵 role을 버리므로(그러면 aria-rowcount·
// aria-rowindex·aria-sort도 얹힐 자리가 없다) 모든 구조 요소에 명시 role을 붙인다.
// role은 grid가 아니라 table이다: 행 클릭은 detail pane 선택일 뿐 셀 단위 키보드 탐색
// (grid가 요구하는 roving tabindex)을 제공하지 않고, e2e 계약도 role=table을 참조한다.
//
// 정적 분석기는 CSS를 못 보므로 이 명시 role을 "암묵 role과 중복"으로 읽는다
// (react-doctor no-redundant-roles / no-interactive-element-to-noninteractive-role).
// 여기서는 display 오버라이드 때문에 중복이 아니라 필수라, 파일 범위 예외를
// `doctor.config.json`에 둔다(같은 파일의 비가상 경로는 native table 그대로다).
function VirtualizedTable<TData>({
  table,
  rows,
  colCount,
  isLoading,
  emptyState,
  skeletonRowCount,
  estimateRowSize,
  overscan,
  onRowClick,
  isRowActive,
  containerClassName,
  ariaLabel,
}: {
  table: TanstackTable<TData>
  rows: Row<TData>[]
  colCount: number
  isLoading?: boolean
  emptyState: DataTableEmptyState
  skeletonRowCount: number
  estimateRowSize: number
  overscan: number
  onRowClick?: (row: TData) => void
  isRowActive?: (row: TData) => boolean
  containerClassName?: string
  ariaLabel?: string
}) {
  "use no memo"

  const containerRef = React.useRef<HTMLDivElement>(null)
  // TanStack Virtual도 동일한 함수형 객체 계약을 가지므로 명시적으로 compiler 경계를 둔다.
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => containerRef.current,
    estimateSize: () => estimateRowSize,
    overscan,
    measureElement:
      typeof window !== "undefined" && !navigator.userAgent.includes("Firefox")
        ? (element) => element?.getBoundingClientRect().height
        : undefined,
  })

  // ARIA rowcount/rowindex는 header row까지 포함해야 스크린리더가 전체 개수와 각 행의
  // 절대 위치를 정확히 읽는다(WAI-ARIA grid). header group(보통 1) + data rows.
  const headerRowCount = table.getHeaderGroups().length
  const leafColumns = table.getAllLeafColumns()
  const skeletonKeys = Array.from(
    { length: Math.max(1, skeletonRowCount) },
    (_, index) => `skeleton-row-${index + 1}`,
  )

  return (
    <div
      ref={containerRef}
      aria-busy={isLoading || undefined}
      className={cn(
        "relative overflow-auto rounded-panel border border-border bg-card group-data-[slot=card]/card:rounded-none group-data-[slot=card]/card:border-0 group-data-[slot=card]/card:bg-transparent",
        containerClassName,
      )}
    >
      <table
        aria-label={ariaLabel}
        aria-rowcount={rows.length + headerRowCount}
        aria-colcount={colCount}
        className="grid w-full caption-bottom text-sm tabular-nums"
        role="table"
      >
        <thead
          className="sticky top-0 z-10 grid bg-surface-subtle [&_tr]:border-b"
          role="rowgroup"
        >
          {table.getHeaderGroups().map((headerGroup, headerGroupIndex) => (
            <tr
              key={headerGroup.id}
              aria-rowindex={headerGroupIndex + 1}
              className="flex w-full border-b border-border"
              role="row"
            >
              {headerGroup.headers.map((header) => {
                const sorted = header.column.getIsSorted()
                const canSort = header.column.getCanSort()
                const meta = columnMeta(header.column)
                return (
                  <th
                    key={header.id}
                    aria-sort={canSort ? ariaSort(sorted) : undefined}
                    role="columnheader"
                    style={{ width: header.getSize() }}
                    className={cn(
                      "flex h-9 items-center px-3 text-left align-middle text-2xs leading-none font-semibold whitespace-nowrap text-text-secondary",
                      flexAlignClass(meta.align),
                      meta.className,
                      meta.headerClassName,
                    )}
                  >
                    {renderHeadCellContent(header, sorted, canSort)}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody
          className="relative grid"
          style={isLoading ? undefined : { height: `${virtualizer.getTotalSize()}px` }}
          role="rowgroup"
        >
          {isLoading ? (
            skeletonKeys.map((rowKey, rowIndex) => (
              <tr
                key={rowKey}
                className="flex w-full border-b border-border"
                role="row"
              >
                {leafColumns.map((column, columnIndex) => {
                  const meta = columnMeta(column)
                  return (
                    <td
                      key={`${rowKey}-${column.id}`}
                      role="cell"
                      style={{ width: column.getSize() }}
                      className={cn(
                        "flex items-center px-3 py-2 align-middle",
                        flexAlignClass(meta.align),
                      )}
                    >
                      <Skeleton className={cn("h-4", skeletonWidth(rowIndex, columnIndex))} />
                    </td>
                  )
                })}
              </tr>
            ))
          ) : rows.length === 0 ? (
            <tr className="flex" role="row">
              <td className="flex w-full px-3" colSpan={colCount} role="cell">
                <EmptyState
                  action={emptyState.action}
                  description={emptyState.description}
                  icon={emptyState.icon}
                  size="sm"
                  title={emptyState.title}
                />
              </td>
            </tr>
          ) : (
            virtualizer.getVirtualItems().map((virtualRow) => {
              const row = rows[virtualRow.index]
              const active = row.getIsSelected() || isRowActive?.(row.original) === true
              return (
                <tr
                  key={row.id}
                  data-index={virtualRow.index}
                  aria-rowindex={virtualRow.index + headerRowCount + 1}
                  aria-selected={onRowClick ? active : undefined}
                  ref={(node) => virtualizer.measureElement(node)}
                  data-state={active ? "selected" : undefined}
                  role="row"
                  className={cn(
                    "absolute flex w-full border-b border-border transition-[color,background-color,border-color] hover:bg-surface-subtle data-[state=selected]:bg-brand-tint",
                    onRowClick && CLICKABLE_ROW_CLASS,
                  )}
                  style={{ transform: `translateY(${virtualRow.start}px)` }}
                  tabIndex={onRowClick ? 0 : undefined}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (event) => handleClickableRowKeyDown(event, row.original, onRowClick)
                      : undefined
                  }
                >
                  {row.getVisibleCells().map((cell: Cell<TData, unknown>) => {
                    const meta = columnMeta(cell.column)
                    return (
                      <td
                        key={cell.id}
                        role="cell"
                        style={{ width: cell.column.getSize() }}
                        className={cn(
                          "flex items-center px-3 py-2 align-middle text-text-primary",
                          flexAlignClass(meta.align),
                          meta.wrap ? "whitespace-normal" : "whitespace-nowrap",
                          meta.className,
                          meta.cellClassName,
                        )}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    )
                  })}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
