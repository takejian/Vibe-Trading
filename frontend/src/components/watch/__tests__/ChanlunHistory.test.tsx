import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChanlunHistory } from "../ChanlunHistory";

const listChanlun = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listChanlun: (...args: unknown[]) => listChanlun(...args),
    },
  };
});

function row(over: Record<string, unknown>) {
  return {
    id: "id",
    run_id: "run-1",
    symbol: "600519.SH",
    analyzed_at: "2026-09-10 11:00:00",
    dim1_structure_read: null,
    dim2_active_pivots: null,
    dim3_divergence: null,
    dim4_buy_sell_points: null,
    dim5_multi_level_plan: null,
    dim6_elliott_corroboration: null,
    dim7_chanlun_score: null,
    score: 3,
    confidence: 0.78,
    structured: true,
    raw_report: null,
    created_at: "2026-09-10 11:00:00",
    ...over,
  };
}

const ROWS = [
  row({
    id: "new",
    run_id: "run-new",
    analyzed_at: "2026-09-10 11:00:00",
    score: 3,
    confidence: 0.78,
    dim1_structure_read: "上行结构完好",
    dim7_chanlun_score: "+3",
  }),
  row({
    id: "old",
    run_id: "run-old",
    analyzed_at: "2026-08-01 09:00:00",
    score: -2,
    confidence: 0.5,
  }),
  row({
    id: "raw",
    run_id: "run-raw",
    analyzed_at: "2026-07-01 09:00:00",
    score: null,
    confidence: null,
    structured: false,
    raw_report: "# raw non-structured report body",
  }),
];

describe("ChanlunHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listChanlun.mockResolvedValue({ items: ROWS });
  });

  it("renders newest-first rows with +/- score coloring and percent confidence", async () => {
    render(<ChanlunHistory symbol="600519.SH" />);
    await waitFor(() => expect(screen.getByText("run-new")).toBeInTheDocument());
    const scores = screen.getAllByTestId("chanlun-score");
    expect(scores[0].textContent).toBe("+3");
    expect(scores[0].className).toContain("red");
    expect(scores[1].textContent).toBe("-2");
    expect(scores[1].className).toContain("green");
    expect(screen.getByText("78%")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(listChanlun).toHaveBeenCalledWith("600519.SH", {
      from: undefined,
      to: undefined,
      limit: 50,
    });
  });

  it("expands a structured row showing the 7 bilingual dimensions in fixed order", async () => {
    const user = userEvent.setup();
    render(<ChanlunHistory symbol="600519.SH" />);
    await screen.findByText("run-new");

    const expand = screen.getAllByRole("button", { name: "Expand" })[0];
    await user.click(expand);

    const titles = Array.from(document.querySelectorAll("dt")).map(
      (el) => el.textContent,
    );
    // Fixed order 1..7.
    expect(titles).toEqual([
      "结构读取 / Structure Read",
      "活跃支点 / Active Pivots",
      "背驰 / Divergence",
      "买卖点 / Buy/Sell Points",
      "多级别计划 / Multi-level Plan",
      "艾略特验证 / Elliott Corroboration",
      "缠论打分 / Chanlun Score",
    ]);
    expect(screen.getByText("上行结构完好")).toBeInTheDocument();
  });

  it("shows the raw report plus a notice for unstructured rows", async () => {
    const user = userEvent.setup();
    render(<ChanlunHistory symbol="600519.SH" />);
    await screen.findByText("run-raw");
    await user.click(screen.getAllByRole("button", { name: "Expand" })[2]);
    expect(screen.getByText("Non-structured response — raw text below")).toBeInTheDocument();
    expect(screen.getByText(/raw non-structured report body/)).toBeInTheDocument();
  });

  it("filters with the selected date range", async () => {
    render(<ChanlunHistory symbol="600519.SH" />);
    await screen.findByText("run-new");
    fireEvent.change(screen.getByTestId("chanlun-from"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(screen.getByTestId("chanlun-to"), {
      target: { value: "2026-09-30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    await waitFor(() =>
      expect(listChanlun).toHaveBeenLastCalledWith("600519.SH", {
        from: "2026-09-01",
        to: "2026-09-30",
        limit: 50,
      }),
    );
  });

  it("renders an empty state", async () => {
    listChanlun.mockResolvedValue({ items: [] });
    render(<ChanlunHistory symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("chanlun-empty")).toBeInTheDocument(),
    );
  });
});
