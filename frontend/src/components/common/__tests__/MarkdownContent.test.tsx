import { render } from "@testing-library/react";
import { MarkdownContent, MarkdownErrorBoundary } from "../MarkdownContent";

// Real react-markdown / remark-gfm pipeline (no mocks): verifies the
// normalized business-document rendering used by chat and the swarm
// run views.

describe("MarkdownContent shared renderer", () => {
  it("renders a normalized GFM table with headers, rows and alignment", () => {
    const markdown = [
      "| 证据 | 状态 | 涨幅 |",
      "| :--- | :---: | ---: |",
      "| 创业板指 | 已验证 | 12% |",
      "| 宏观读数 | 方向性 | 3% |",
    ].join("\n");
    const { container } = render(<MarkdownContent content={markdown} />);

    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    // Horizontal scroll wrapper keeps wide tables inside the panel.
    expect(table?.parentElement).toHaveClass("overflow-x-auto");

    const headers = Array.from(container.querySelectorAll("thead th"));
    expect(headers.map((th) => th.textContent)).toEqual([
      "证据",
      "状态",
      "涨幅",
    ]);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
    // GFM column alignment is reflected on cells (react-markdown v9 emits
    // inline text-align styles rather than the deprecated align attribute).
    expect(headers[0]).toHaveStyle({ "text-align": "left" });
    expect(headers[1]).toHaveStyle({ "text-align": "center" });
    expect(headers[2]).toHaveStyle({ "text-align": "right" });
  });

  it("applies prose document styling and semantic elements", () => {
    const markdown = [
      "# 一、结论",
      "",
      "倾向**做多**，依据如下：",
      "",
      "- 估值处于低位",
      "- 资金持续流入",
      "",
      "1. 建仓 `600519.SH`",
      "2. 设置止损",
    ].join("\n");
    const { container } = render(<MarkdownContent content={markdown} />);

    const prose = container.querySelector(".prose");
    expect(prose).not.toBeNull();
    expect(container.querySelector("h1")?.textContent).toBe("一、结论");
    expect(container.querySelector("ul li")).not.toBeNull();
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("做多");
    expect(container.querySelector("code")?.textContent).toBe("600519.SH");
    // Table styling hooks are present on the prose container.
    expect(prose?.className).toContain("prose-table:border");
    expect(prose?.className).toContain("prose-th:bg-muted/30");
  });

  it("degrades a malformed table fragment to plain text without breaking the rest", () => {
    const markdown = [
      "## 标题仍应渲染",
      "",
      "| 只有表头 | 没有分隔行",
      "普通段落内容保留",
    ].join("\n");
    const { container } = render(<MarkdownContent content={markdown} />);

    expect(container.querySelector("table")).toBeNull();
    expect(container.querySelector("h2")?.textContent).toBe("标题仍应渲染");
    expect(container.textContent).toContain("普通段落内容保留");
    expect(container.textContent).toContain("只有表头");
  });

  it("renders links with safe external attributes", () => {
    const { container } = render(
      <MarkdownContent content={"[研报原文](https://example.com/r)"} />,
    );
    const link = container.querySelector("a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("falls back to plain text when a render child throws", () => {
    function Boom(): never {
      throw new Error("render failure");
    }
    const { container } = render(
      <MarkdownErrorBoundary content={"第一行\n第二行"}>
        <Boom />
      </MarkdownErrorBoundary>,
    );
    const fallback = container.querySelector(".whitespace-pre-wrap");
    expect(fallback).not.toBeNull();
    expect(fallback?.textContent).toBe("第一行\n第二行");
  });
});
