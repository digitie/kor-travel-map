// @vitest-environment jsdom
import { type ColumnDef } from "@tanstack/react-table";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DataTable } from "./data-table";

interface Row {
  id: string;
  name: string;
  score: number;
}

const columns: ColumnDef<Row, unknown>[] = [
  { accessorKey: "name", header: "name" },
  { accessorKey: "score", header: "score" },
  {
    id: "actions",
    header: "actions",
    enableSorting: false,
    cell: () => (
      <button type="button">행 동작</button>
    ),
  },
];

const data: Row[] = [
  { id: "a", name: "베타", score: 2 },
  { id: "b", name: "알파", score: 5 },
];

const getRowId = (row: Row) => row.id;

afterEach(() => cleanup());

describe("DataTable", () => {
  it("renders semantic columnheaders with verbatim header text + header/data rows", () => {
    render(<DataTable columns={columns} data={data} getRowId={getRowId} />);

    // 헤더 텍스트가 columnheader 접근성 이름으로 보존된다(Playwright 셀렉터 계약).
    expect(screen.getByRole("columnheader", { name: "name" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "score" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "actions" })).toBeTruthy();
    // 헤더 row 1 + 데이터 row 2.
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("sortable header toggles aria-sort and reorders rows (client sort)", () => {
    // manualSorting 기본이 true(서버 정렬)로 뒤집혔으므로(#502), client 정렬을 실제로
    // 검증하려면 완전 client 목록처럼 명시적으로 끈다.
    render(
      <DataTable
        columns={columns}
        data={data}
        getRowId={getRowId}
        manualSorting={false}
      />,
    );

    const nameHeader = screen.getByRole("columnheader", { name: "name" });
    expect(nameHeader.getAttribute("aria-sort")).toBe("none");

    // 첫 클릭 → 오름차순. 한글 기본 정렬에서 '베타'(initial) 순서가 바뀐다.
    fireEvent.click(within(nameHeader).getByRole("button"));
    expect(nameHeader.getAttribute("aria-sort")).toBe("ascending");

    // 두 번째 클릭 → 내림차순.
    fireEvent.click(within(nameHeader).getByRole("button"));
    expect(nameHeader.getAttribute("aria-sort")).toBe("descending");
  });

  it("non-sortable column exposes no aria-sort and no sort button", () => {
    render(<DataTable columns={columns} data={data} getRowId={getRowId} />);
    const actionsHeader = screen.getByRole("columnheader", { name: "actions" });
    expect(actionsHeader.getAttribute("aria-sort")).toBeNull();
    // header 셀에는 정렬 버튼이 없다(actions는 enableSorting:false). 행의 '행 동작' 버튼만 존재.
    expect(within(actionsHeader).queryByRole("button")).toBeNull();
  });

  it("shows the empty message when data is empty", () => {
    render(
      <DataTable
        columns={columns}
        data={[]}
        getRowId={getRowId}
        emptyMessage="데이터가 없습니다."
      />,
    );
    expect(screen.getByText("데이터가 없습니다.")).toBeTruthy();
  });

  it("renders the error alert when isError", () => {
    render(
      <DataTable
        columns={columns}
        data={[]}
        getRowId={getRowId}
        isError
        error={{ message: "불러오기 실패함" }}
      />,
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("불러오기 실패함")).toBeTruthy();
  });

  it("rowTestId renders a per-row data-testid on each row", () => {
    render(
      <DataTable
        columns={columns}
        data={data}
        getRowId={getRowId}
        rowTestId={() => "sample-row"}
      />,
    );
    expect(screen.getAllByTestId("sample-row")).toHaveLength(2);
  });

  it("getCanSelect predicate disables non-selectable row checkboxes", () => {
    render(
      <DataTable
        columns={columns}
        data={data}
        getRowId={getRowId}
        enableRowSelection={(row) => row.original.score > 3}
      />,
    );
    // data: 베타(score 2)는 선택 불가, 알파(score 5)는 선택 가능 → 행 체크박스 2개 중 1개 disabled.
    const rowCheckboxes = screen.getAllByLabelText("행 선택");
    expect(rowCheckboxes).toHaveLength(2);
    const disabled = rowCheckboxes.filter(
      (cb) =>
        cb.hasAttribute("disabled") ||
        cb.getAttribute("aria-disabled") === "true" ||
        cb.hasAttribute("data-disabled"),
    );
    expect(disabled).toHaveLength(1);
  });
});
