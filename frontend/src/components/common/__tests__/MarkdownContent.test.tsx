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
    // Tables fit the page width with a fixed layout and wrap cell text
    // instead of forcing a horizontal scrollbar.
    expect(table).toHaveClass("w-full", "table-fixed");
    expect(table?.parentElement).toHaveClass("min-w-0", "max-w-full");
    expect(table?.parentElement).not.toHaveClass("overflow-x-auto");

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

  it("wraps fenced code blocks to the page width without horizontal scroll", () => {
    const longLine = "x".repeat(300);
    const markdown = "```text\n" + longLine + "\n```";
    const { container } = render(<MarkdownContent content={markdown} />);

    expect(container.querySelector("pre")).not.toBeNull();
    // The wrapping rules are emitted as arbitrary variants on the prose
    // container targeting pre (Tailwind generates descendant selectors).
    const prose = container.querySelector(".prose");
    expect(prose?.className).toContain("[&_pre]:whitespace-pre-wrap");
    expect(prose?.className).toContain("[&_pre]:overflow-x-hidden");
  });

  it("breaks long unbroken words and URLs in body text", () => {
    const markdown =
      "详情见 https://example.com/" + "a".repeat(200) + " 这是正常文本。";
    const { container } = render(<MarkdownContent content={markdown} />);

    const prose = container.querySelector(".prose");
    expect(prose).toHaveClass("break-words", "min-w-0");
  });

  it("allows inline code tokens to wrap", () => {
    const markdown = "令牌 `" + "a".repeat(200) + "` 已失效。";
    const { container } = render(<MarkdownContent content={markdown} />);

    expect(container.querySelector("p code")).not.toBeNull();
    const prose = container.querySelector(".prose");
    expect(prose?.className).toContain("[&_code]:[overflow-wrap:anywhere]");
  });
});
