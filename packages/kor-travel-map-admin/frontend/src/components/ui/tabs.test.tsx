// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { Tabs, TabsList, TabsTrigger } from "./tabs";

afterEach(cleanup);

it("탭 트리거 focus는 공통 0.2.4의 단일 outline 2px·offset 2px 한 벌뿐이다(FS-7.8)", () => {
  render(
    <Tabs defaultValue="a">
      <TabsList>
        <TabsTrigger value="a">가</TabsTrigger>
      </TabsList>
    </Tabs>,
  );
  const tokens = screen.getByRole("tab", { name: "가" }).className.split(/\s+/);
  // focus-visible 변형은 정확히 이 셋 — ring·테두리 색·1px outline이 다시 끼어들면 실패한다.
  expect(tokens.filter((token) => token.startsWith("focus-visible:")).sort()).toEqual([
    "focus-visible:outline-2",
    "focus-visible:outline-kt-focus",
    "focus-visible:outline-offset-2",
  ]);
  expect(tokens.filter((token) => /(^|:)ring(-|$)/.test(token))).toEqual([]);
  expect(tokens).not.toContain("transition-all");
});
