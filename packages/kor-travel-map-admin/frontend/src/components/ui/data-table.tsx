"use client"

// 공용 headless DataTable — @tanstack/react-table v8(STABLE) 기반. admin/ops UI의 모든
// 테이블이 본 컴포넌트로 통일된다(ADR/마이그레이션 2026-06-17). 기본은 semantic
// shadcn Table primitive로 렌더해 접근성(role=table/columnheader/row/cell)과 기존
// Playwright 셀렉터를 보존하고, 대용량/무한 목록만 `virtualized`로 @tanstack/react-virtual
// 윈도잉을 켠다(이때는 display:grid라 native table role이 죽으므로 명시 ARIA를 붙인다).
//
// 데이터 연산은 기본 server-side(manual*): 페이지의 react-query가 이미 cursor 페이징/
// 필터/정렬을 수행하므로 DataTable은 data만 받아 렌더한다. 완전 client 목록은
// manualSorting={false}로 getSortedRowModel을 켤 수 있다.

import * as React from "react"
import {
  type Cell,
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

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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

export interface DataTableProps<TData> {
  columns: ColumnDef<TData, unknown>[]
  data: TData[]
  /** row.id를 도메인 안정 id로 고정(권장) — 정렬/선택/가상화 키 안정성. */
  getRowId?: (row: TData, index: number) => string
  /** react-query 상태를 그대로 넘기면 skeleton/alert/empty를 내부에서 렌더. */
  isLoading?: boolean
  isError?: boolean
  error?: { message?: string } | null
  /** 비었을 때 colSpan 행에 표시할 문구. */
  emptyMessage?: string
  /** 정렬: 제어(서버) 모드면 sorting+onSortingChange 전달 + manualSorting. */
  sorting?: SortingState
  onSortingChange?: OnChangeFn<SortingState>
  /** true면 getSortedRowModel을 켜지 않음(서버 정렬). 기본 false(클라 정렬). */
  manualSorting?: boolean
  /** 행 선택(opt-in) — 체크박스 컬럼 + 선택 상태. */
  enableRowSelection?: boolean
  rowSelection?: RowSelectionState
  onRowSelectionChange?: OnChangeFn<RowSelectionState>
  /** 선택된 행이 있을 때 테이블 위에 표시할 bulk action 바. */
  renderBulkActions?: (rows: Row<TData>[]) => React.ReactNode
  /** 행 클릭(detail pane 선택 등). 내부 link/button은 stopPropagation 해야 함. */
  onRowClick?: (row: TData) => void
  /** 행 active(detail pane 강조) — data-state="selected". */
  isRowActive?: (row: TData) => boolean
  /** 가상화(대용량/무한 목록만). 켜면 명시 ARIA + display:grid 레이아웃. */
  virtualized?: boolean
  estimateRowSize?: number
  overscan?: number
  /** 스크롤 컨테이너 className(가상화 시 고정 높이 필수, 예: h-[calc(100vh-16rem)]). */
  containerClassName?: string
  /** 테이블 caption(스크린리더용). */
  ariaLabel?: string
}

/** 정렬 가능한 헤더 버튼 — 접근성 이름은 title 그대로 보존(글리프 aria-hidden), th에 aria-sort. */
export function DataTableColumnHeader({
  title,
  sorted,
  canSort,
  onToggle,
}: {
  title: string
  sorted: false | "asc" | "desc"
  canSort: boolean
  onToggle?: (event: React.MouseEvent) => void
}) {
  if (!canSort) return <>{title}</>
  const Glyph = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ChevronsUpDown
  return (
    <Button
      variant="ghost"
      size="sm"
      className="-ml-2 h-7 px-2 data-[state=open]:bg-accent"
      onClick={onToggle}
    >
      {title}
      <Glyph className="ml-1 size-3.5 opacity-60" aria-hidden="true" />
    </Button>
  )
}

function ariaSort(sorted: false | "asc" | "desc"): "ascending" | "descending" | "none" {
  if (sorted === "asc") return "ascending"
  if (sorted === "desc") return "descending"
  return "none"
}

function selectionColumn<TData>(): ColumnDef<TData, unknown> {
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
        aria-label="행 선택"
        checked={row.getIsSelected()}
        disabled={!row.getCanSelect()}
        onCheckedChange={(checked) => row.toggleSelected(!!checked)}
        onClick={(event) => event.stopPropagation()}
      />
    ),
  }
}

export function DataTable<TData>({
  columns,
  data,
  getRowId,
  isLoading,
  isError,
  error,
  emptyMessage = "데이터가 없습니다.",
  sorting,
  onSortingChange,
  manualSorting = false,
  enableRowSelection = false,
  rowSelection,
  onRowSelectionChange,
  renderBulkActions,
  onRowClick,
  isRowActive,
  virtualized = false,
  estimateRowSize = 40,
  overscan = 12,
  containerClassName,
  ariaLabel,
}: DataTableProps<TData>) {
  const [internalSorting, setInternalSorting] = React.useState<SortingState>([])
  const [internalSelection, setInternalSelection] = React.useState<RowSelectionState>({})

  const resolvedColumns = React.useMemo(
    () => (enableRowSelection ? [selectionColumn<TData>(), ...columns] : columns),
    [columns, enableRowSelection],
  )

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
    return (
      <Alert variant="destructive">
        <AlertTitle>불러오기 실패</AlertTitle>
        <AlertDescription>{error?.message ?? "알 수 없는 오류"}</AlertDescription>
      </Alert>
    )
  }

  const rows = table.getRowModel().rows
  const colCount = table.getAllLeafColumns().length
  const selectedRows = enableRowSelection ? table.getSelectedRowModel().rows : []

  const bulkBar =
    enableRowSelection && renderBulkActions && selectedRows.length > 0 ? (
      <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-2 py-1.5 text-sm">
        <span className="text-muted-foreground">{selectedRows.length}개 선택됨</span>
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
          emptyMessage={emptyMessage}
          estimateRowSize={estimateRowSize}
          overscan={overscan}
          onRowClick={onRowClick}
          isRowActive={isRowActive}
          containerClassName={containerClassName}
          ariaLabel={ariaLabel}
        />
      ) : (
        <div className={cn(containerClassName)}>
          <Table aria-label={ariaLabel}>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <PlainHeadCell key={header.id} header={header} />
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <SkeletonRows colCount={colCount} />
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={colCount}
                    className="h-32 text-center text-muted-foreground"
                  >
                    {emptyMessage}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow
                    key={row.id}
                    data-state={
                      row.getIsSelected() || isRowActive?.(row.original)
                        ? "selected"
                        : undefined
                    }
                    className={onRowClick ? "cursor-pointer" : undefined}
                    onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

function PlainHeadCell<TData>({ header }: { header: Header<TData, unknown> }) {
  const sorted = header.column.getIsSorted()
  const canSort = header.column.getCanSort()
  return (
    <TableHead aria-sort={canSort ? ariaSort(sorted) : undefined}>
      {header.isPlaceholder ? null : typeof header.column.columnDef.header === "string" ? (
        <DataTableColumnHeader
          title={header.column.columnDef.header}
          sorted={sorted}
          canSort={canSort}
          onToggle={header.column.getToggleSortingHandler()}
        />
      ) : (
        flexRender(header.column.columnDef.header, header.getContext())
      )}
    </TableHead>
  )
}

function SkeletonRows({ colCount }: { colCount: number }) {
  return (
    <>
      {Array.from({ length: 8 }).map((_, rowIndex) => (
        <TableRow key={rowIndex}>
          {Array.from({ length: colCount }).map((__, colIndex) => (
            <TableCell key={colIndex}>
              <Skeleton className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

// 가상화 변형 — display:grid + sticky thead + absolute rows. native table role이 죽으므로
// 명시 role/aria-rowcount/aria-rowindex를 붙여 스크린리더가 전체 개수를 인지하게 한다.
function VirtualizedTable<TData>({
  table,
  rows,
  colCount,
  isLoading,
  emptyMessage,
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
  emptyMessage: string
  estimateRowSize: number
  overscan: number
  onRowClick?: (row: TData) => void
  isRowActive?: (row: TData) => boolean
  containerClassName?: string
  ariaLabel?: string
}) {
  const containerRef = React.useRef<HTMLDivElement>(null)
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

  return (
    <div
      ref={containerRef}
      className={cn("relative overflow-auto rounded-md border", containerClassName)}
    >
      <table
        role="table"
        aria-label={ariaLabel}
        aria-rowcount={rows.length}
        className="grid w-full caption-bottom text-sm"
      >
        <thead
          role="rowgroup"
          className="sticky top-0 z-10 grid bg-background [&_tr]:border-b"
        >
          {table.getHeaderGroups().map((headerGroup) => (
            <tr role="row" key={headerGroup.id} className="flex w-full border-b">
              {headerGroup.headers.map((header) => {
                const sorted = header.column.getIsSorted()
                const canSort = header.column.getCanSort()
                return (
                  <th
                    role="columnheader"
                    key={header.id}
                    aria-sort={canSort ? ariaSort(sorted) : undefined}
                    style={{ width: header.getSize() }}
                    className="flex h-10 items-center px-2 text-left align-middle font-medium text-foreground"
                  >
                    {header.isPlaceholder
                      ? null
                      : typeof header.column.columnDef.header === "string"
                        ? (
                          <DataTableColumnHeader
                            title={header.column.columnDef.header}
                            sorted={sorted}
                            canSort={canSort}
                            onToggle={header.column.getToggleSortingHandler()}
                          />
                        )
                        : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody
          role="rowgroup"
          className="relative grid"
          style={{ height: `${virtualizer.getTotalSize()}px` }}
        >
          {isLoading ? null : rows.length === 0 ? (
            <tr role="row" className="flex">
              <td
                role="cell"
                className="flex h-32 w-full items-center justify-center text-muted-foreground"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            virtualizer.getVirtualItems().map((virtualRow) => {
              const row = rows[virtualRow.index]
              return (
                <tr
                  role="row"
                  key={row.id}
                  data-index={virtualRow.index}
                  aria-rowindex={virtualRow.index + 1}
                  ref={(node) => virtualizer.measureElement(node)}
                  data-state={
                    row.getIsSelected() || isRowActive?.(row.original) ? "selected" : undefined
                  }
                  className={cn(
                    "absolute flex w-full border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted",
                    onRowClick && "cursor-pointer",
                  )}
                  style={{ transform: `translateY(${virtualRow.start}px)` }}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                >
                  {row.getVisibleCells().map((cell: Cell<TData, unknown>) => (
                    <td
                      role="cell"
                      key={cell.id}
                      style={{ width: cell.column.getSize() }}
                      className="flex items-center p-2 align-middle"
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
      {isLoading ? (
        <div className="p-2">
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}
    </div>
  )
}
