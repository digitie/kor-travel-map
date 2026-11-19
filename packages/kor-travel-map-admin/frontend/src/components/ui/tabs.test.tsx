// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { Tabs, TabsList, TabsTrigger } from "./tabs";

afterEach(cleanup);

it("탭 트리거 focus는 단일 outline 2px이고 공통 recipe의 ring·테두리 색·1px outline이 남지 않는다(FS-7.8)", () => {
  render(
    <Tabs defaultValue="a">
      <TabsList>
        <TabsTrigger value="a">가</TabsTrigger>
      </TabsList>
    </Tabs>,
  );
  const tokens = screen.getByRole("tab", { name: "가" }).className.split(" ");
  const focus = tokens.filter((token) => token.startsWith("focus-visible:")).toSorted();
  expect(focus).toEqual([
    "focus-visible:border-transparent",
    "focus-visible:outline-2",
    "focus-visible:outline-focus",
    "focus-visible:outline-offset-2",
    "focus-visible:ring-0",
  ]);
  expect(tokens).not.toContain("transition-all");
});
