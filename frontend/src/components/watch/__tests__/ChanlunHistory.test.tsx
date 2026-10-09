import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChanlunHistory } from "../ChanlunHistory";

const listChanlun = vi.fn();
const getChanlunStats = vi.fn();
const compareChanlunCards = vi.fn();
const rateChanlunCard = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listChanlun: (...args: unknown[]) => listChanlun(...args),
      getChanlunStats: (...args: unknown[]) => getChanlunStats(...args),
      compareChanlunCards: (...args: unknown[]) => compareChanlunCards(...args),
      rateChanlunCard: (...args: unknown[]) => rateChanlunCard(...args),
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
    getChanlunStats.mockResolvedValue({
      cards_total: 0, verified_decided: 0, wins: 0, losses: 0, partials: 0,
      win_rate: null, direction_accuracy: null, target_hit_rate: null,
      stop_rate: null, avg_mfe_pct: null, avg_mae_pct: null,
      ratings: { accurate: 0, partial: 0, wrong: 0 }, rated_total: 0,
      pending: 0, insufficient_data: 0, neutral: 0, by_setup: {},
    });
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

function cardRow(over: Record<string, unknown>) {
  return row({
    score: 3,
    confidence: 0.65,
    card_parse: "ok",
    base_price: 10.0,
    base_date: "2026-08-01",
    direction: "bullish",
    action: "buy",
    setup_class: "3买",
    card_confidence: 65,
    horizon_days: 10,
    trigger_price: 10.2,
    stop_price: 9.8,
    target_prices: [10.8],
    rr_at_t1: 1.5,
    invalidation: "破9.8",
    key_risks: "大盘补跌",
    one_liner: "日线三买，回踩确认",
    card_json: "{}",
    live_status: "target_hit",
    eval_status: "verified",
    outcome_label: "win",
    window_end_date: "2026-08-15",
    target_hit: true,
    stop_hit: false,
    first_event: "target_first",
    mfe_pct: 7.2,
    mae_pct: -1.1,
    exit_return_pct: 6.9,
    direction_correct: true,
    error_note: null,
    evaluated_at: null,
    user_verdict: null,
    user_note: null,
    user_rated_at: null,
    ...over,
  });
}

describe("Chanlun action-card closed loop", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getChanlunStats.mockResolvedValue({
      cards_total: 2, verified_decided: 2, wins: 1, losses: 1, partials: 0,
      win_rate: 50, direction_accuracy: 100, target_hit_rate: 50,
      stop_rate: 50, avg_mfe_pct: 6.1, avg_mae_pct: -2.3,
      ratings: { accurate: 0, partial: 0, wrong: 0 }, rated_total: 0,
      pending: 0, insufficient_data: 0, neutral: 0,
      by_setup: { "3买": { total: 2, win: 1, loss: 1, partial: 0 } },
    });
  });

  it("shows the track-record stats strip with win rate", async () => {
    listChanlun.mockResolvedValue({ items: [cardRow({ id: "c1", run_id: "r1" })] });
    render(<ChanlunHistory symbol="600519.SH" />);
    const strip = await screen.findByTestId("chanlun-stats");
    expect(strip.textContent).toContain("Win rate");
    expect(strip.textContent).toContain("50%");
  });

  it("renders card mini summary, live status and machine outcome", async () => {
    listChanlun.mockResolvedValue({
      items: [cardRow({ id: "c1", run_id: "r1" })],
    });
    render(<ChanlunHistory symbol="600519.SH" />);
    await screen.findByTestId("card-mini");
    expect(screen.getByText("Bullish")).toBeInTheDocument();
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("日线三买，回踩确认")).toBeInTheDocument();
    expect(screen.getByTestId("row-live-status").textContent).toBe("T1 reached");
    expect(screen.getByTestId("row-outcome").textContent).toContain("Win realized");
    expect(screen.getByTestId("row-outcome").textContent).toContain("+6.9%");
  });

  it("lets the investor submit a post-hoc rating from the expanded card", async () => {
    listChanlun.mockResolvedValue({
      items: [cardRow({ id: "c1", run_id: "r1" })],
    });
    rateChanlunCard.mockResolvedValue({
      user_verdict: "accurate",
      user_rated_at: "2026-09-01 10:00:00",
    });
    const user = userEvent.setup();
    render(<ChanlunHistory symbol="600519.SH" />);
    await screen.findByTestId("card-mini");
    await user.click(screen.getAllByRole("button", { name: "Expand" })[0]);

    const card = await screen.findByTestId("chanlun-action-card");
    expect(card.textContent).toContain("10.20");
    expect(card.textContent).toContain("9.80");

    await user.click(screen.getByTestId("rate-accurate"));
    fireEvent.change(screen.getByTestId("rate-note"), {
      target: { value: "按计划触发" },
    });
    await user.click(screen.getByTestId("rate-save"));
    await waitFor(() =>
      expect(rateChanlunCard).toHaveBeenCalledWith(
        "600519.SH", "r1", "accurate", "按计划触发",
      ),
    );
  });

  it("compares 2-4 selected cards in a side-by-side panel", async () => {
    listChanlun.mockResolvedValue({
      items: [
        cardRow({ id: "c1", run_id: "run-new", one_liner: "三买", direction: "bullish" }),
        cardRow({
          id: "c2", run_id: "run-old", one_liner: "一卖",
          direction: "bearish", action: "sell", live_status: "stopped",
          outcome_label: "loss",
        }),
      ],
    });
    compareChanlunCards.mockResolvedValue({
      items: [
        cardRow({ id: "c1", run_id: "run-new", one_liner: "三买", direction: "bullish" }),
        cardRow({
          id: "c2", run_id: "run-old", one_liner: "一卖",
          direction: "bearish", action: "sell", live_status: "stopped",
          outcome_label: "loss",
        }),
      ],
    });
    const user = userEvent.setup();
    render(<ChanlunHistory symbol="600519.SH" />);
    await screen.findAllByTestId("card-mini");

    await user.click(screen.getByTestId("compare-pick-run-new"));
    await user.click(screen.getByTestId("compare-pick-run-old"));
    await user.click(screen.getByTestId("compare-go"));

    await waitFor(() =>
      expect(compareChanlunCards).toHaveBeenCalledWith(
        "600519.SH", ["run-new", "run-old"],
      ),
    );
    const panel = await screen.findByTestId("chanlun-compare-panel");
    expect(panel.textContent).toContain("run-new");
    expect(panel.textContent).toContain("run-old");
    // Differing direction cell is highlighted.
    const dirCells = screen.getAllByTestId("compare-cell-direction");
    expect(dirCells.length).toBe(2);
  });

  it("disables compare checkboxes for rows without a parsed card", async () => {
    listChanlun.mockResolvedValue({ items: ROWS });
    render(<ChanlunHistory symbol="600519.SH" />);
    await screen.findByText("run-new");
    expect(screen.getByTestId("compare-pick-run-new")).toBeDisabled();
    expect(screen.getByTestId("compare-go")).toBeDisabled();
  });
});
