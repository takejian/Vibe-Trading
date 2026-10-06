import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AnalysisTab } from "../AnalysisTab";

const listWatchAgents = vi.fn();
const listWatchAnalyses = vi.fn();
const startWatchAnalysis = vi.fn();
const getWatchKlineStatus = vi.fn();
const getWatchKlineSources = vi.fn();
const runViewSpy = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listWatchAgents: (...args: unknown[]) => listWatchAgents(...args),
      listWatchAnalyses: (...args: unknown[]) => listWatchAnalyses(...args),
      startWatchAnalysis: (...args: unknown[]) => startWatchAnalysis(...args),
      getWatchKlineStatus: (...args: unknown[]) => getWatchKlineStatus(...args),
      getWatchKlineSources: (...args: unknown[]) => getWatchKlineSources(...args),
    },
  };
});

vi.mock("@/components/swarm/RunView", () => ({
  RunView: (props: { runId: string; readOnly?: boolean; onBack: () => void }) => {
    runViewSpy(props);
    return (
      <div data-testid="mock-run-view">
        RUN {props.runId} {props.readOnly ? "READONLY" : "LIVE"}
        <button type="button" onClick={props.onBack}>
          back
        </button>
      </div>
    );
  },
}));

const CHANLUN_REF = "technical_analysis_panel:chanlun_analyst";
const CLASSIC_REF = "technical_analysis_panel:classic_ta_analyst";

const AGENTS = {
  items: [
    {
      ref: CHANLUN_REF,
      name: "Chanlun (Chan Theory) Analyst",
      purpose: "中枢背驰买卖点",
      category: "technical" as const,
      is_chanlun: true,
      team: "Technical Analysis Panel",
    },
    {
      ref: CLASSIC_REF,
      name: "Classic Technical Analyst",
      purpose: "均线 MACD",
      category: "technical" as const,
      is_chanlun: false,
      team: "Technical Analysis Panel",
    },
  ],
};

function historyItem(over: Record<string, unknown> = {}) {
  return {
    id: "run-h1",
    status: "completed",
    role_ref: "technical_analysis_panel:chanlun_analyst",
    role_name: "Chanlun (Chan Theory) Analyst",
    category: "technical" as const,
    is_chanlun: true,
    research_target: "贵州茅台（600519.SH）",
    research_question: "如何看待当前走势",
    created_at: "2026-09-10T10:00:00+00:00",
    completed_at: "2026-09-10T11:00:00+00:00",
    final_report_excerpt: "EXCERPT-ONLY-SHORT",
    // AC-11: expand renders the FULL conclusion, not the 280-char excerpt.
    final_report: "# 完整结论\n表格与**正文全文**",
    qualified: true,
    ...over,
  };
}

describe("AnalysisTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getWatchKlineSources.mockResolvedValue({
      items: [
        { id: "tencent", available: true, requires_auth: false, reason: null,
          intervals: ["1d", "1w", "1mo", "1q", "1y", "30m"] },
        { id: "eastmoney", available: true, requires_auth: false, reason: null,
          intervals: ["1d", "1w", "1mo", "1q", "1y", "30m"] },
      ],
    });
    listWatchAgents.mockResolvedValue(AGENTS);
    listWatchAnalyses.mockResolvedValue({ items: [] });
    startWatchAnalysis.mockResolvedValue({
      id: "run-new",
      status: "pending",
      kind: "role_run",
      trial_role: AGENTS.items[0].ref,
    });
    getWatchKlineStatus.mockResolvedValue({
      items: [
        { interval: "1d", required: true, status: "ready", fetch_failed: false,
          bars_count: 120, earliest_bar_time: "2026-01-01",
          latest_bar_time: "2026-09-30", last_ok_at: "2026-09-30T15:00:00",
          last_attempt_at: "2026-09-30T15:00:00", last_error: null },
        { interval: "1w", required: true, status: "ready", fetch_failed: false,
          bars_count: 60, earliest_bar_time: null, latest_bar_time: "2026-09-30",
          last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00",
          last_error: null },
        { interval: "1mo", required: true, status: "ready", fetch_failed: false,
          bars_count: 24, earliest_bar_time: null, latest_bar_time: "2026-09-30",
          last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00",
          last_error: null },
        { interval: "1q", required: true, status: "ready", fetch_failed: false,
          bars_count: 12, earliest_bar_time: null, latest_bar_time: "2026-09-30",
          last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00",
          last_error: null },
        { interval: "1y", required: true, status: "ready", fetch_failed: false,
          bars_count: 5, earliest_bar_time: null, latest_bar_time: "2026-09-30",
          last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00",
          last_error: null },
        { interval: "30m", required: false, status: "ready", fetch_failed: false,
          bars_count: 24, earliest_bar_time: null,
          latest_bar_time: "2026-09-30 14:30", last_ok_at: "2026-09-30T15:00:00",
          last_attempt_at: "2026-09-30T15:00:00", last_error: null },
      ],
      market_ref: {
        last_trading_date: "2026-09-30",
        threshold_date: "2026-09-29",
        source: "trading_calendar",
      },
    });
  });

  it("requests the given category catalog and disables run until a role is chosen", async () => {
    const user = userEvent.setup();
    render(
      <AnalysisTab category="technical" symbol="600519.SH" symbolName="贵州茅台" />,
    );
    await waitFor(() =>
      expect(screen.getByText(/Classic Technical Analyst/)).toBeInTheDocument(),
    );
    expect(listWatchAgents).toHaveBeenCalledWith("technical");
    expect(screen.getByTestId("analysis-run-btn")).toBeDisabled();
    expect(screen.getByText("Select exactly one analyst to start")).toBeInTheDocument();
    // Every option labels the source agent team in parentheses.
    expect(
      screen.getByText(/Classic Technical Analyst \(Technical Analysis Panel\)/),
    ).toBeInTheDocument();
    // Chanlun role carries a visual marker once selected.
    await user.selectOptions(screen.getByTestId("analysis-role-select"), CHANLUN_REF);
    expect(screen.getByTestId("chanlun-badge")).toHaveTextContent("Chanlun");
  });

  it("starts an analysis with the selected role; question omitted when empty", async () => {
    const user = userEvent.setup();
    render(<AnalysisTab category="technical" symbol="600519.SH" />);
    await screen.findByText(/Classic Technical Analyst/);

    await user.selectOptions(screen.getByTestId("analysis-role-select"), CLASSIC_REF);
    await user.click(screen.getByTestId("analysis-run-btn"));

    await waitFor(() => expect(startWatchAnalysis).toHaveBeenCalledTimes(1));
    expect(startWatchAnalysis).toHaveBeenCalledWith("600519.SH", {
      category: "technical",
      role_ref: "technical_analysis_panel:classic_ta_analyst",
    });
    // RunView mounts for the new run in live mode (progress can be tracked).
    expect(screen.getByTestId("mock-run-view")).toHaveTextContent("run-new");
    expect(screen.getByTestId("mock-run-view")).toHaveTextContent("LIVE");
  });

  it("sends the optional question when provided", async () => {
    const user = userEvent.setup();
    listWatchAgents.mockResolvedValueOnce({
      items: [
        {
          ref: "g:r",
          name: "Generalist",
          purpose: "",
          category: "general" as const,
          is_chanlun: false,
          team: "",
        },
      ],
    });
    render(<AnalysisTab category="general" symbol="000001.SZ" />);
    await waitFor(() => expect(listWatchAgents).toHaveBeenCalledWith("general"));
    // Custom roles are labelled with the custom-team fallback.
    await screen.findByText(/Generalist \(Custom roles\)/);
    await user.selectOptions(screen.getByTestId("analysis-role-select"), "g:r");
    await user.type(screen.getByTestId("analysis-question"), "关注风险提示");
    await user.click(screen.getByTestId("analysis-run-btn"));
    await waitFor(() =>
      expect(startWatchAnalysis).toHaveBeenCalledWith("000001.SZ", {
        category: "general",
        role_ref: "g:r",
        question: "关注风险提示",
      }),
    );
  });

  it("shows the in-progress message on 409 and renders no duplicate run view", async () => {
    const user = userEvent.setup();
    startWatchAnalysis.mockRejectedValue(new ApiError("busy", 409));
    render(<AnalysisTab category="technical" symbol="600519.SH" />);
    await screen.findByText(/Classic Technical Analyst/);

    await user.selectOptions(screen.getByTestId("analysis-role-select"), CLASSIC_REF);
    await user.click(screen.getByTestId("analysis-run-btn"));

    await waitFor(() =>
      expect(screen.getByTestId("analysis-409")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("mock-run-view")).toBeNull();
    // History reloaded to surface the in-progress card.
    expect(listWatchAnalyses).toHaveBeenCalledTimes(2);
  });

  it("groups history by role, expands the full report, and opens runs of any status", async () => {
    const user = userEvent.setup();
    listWatchAnalyses
      .mockResolvedValueOnce({
        items: [
          historyItem(),
          historyItem({
            id: "run-live",
            status: "running",
            qualified: false,
            final_report_excerpt: "",
            completed_at: null,
          }),
        ],
      })
      // reloaded when the RunView back button is pressed
      .mockResolvedValueOnce({ items: [historyItem()] });

    render(<AnalysisTab category="technical" symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getAllByText("如何看待当前走势").length).toBe(2),
    );

    // One role group header.
    expect(screen.getAllByText("Chanlun (Chan Theory) Analyst").length).toBeGreaterThan(0);

    // Expand the completed row -> FULL markdown report rendered (not excerpt).
    await user.click(screen.getAllByRole("button", { expanded: false })[0]);
    await waitFor(() => expect(screen.getByText("完整结论")).toBeInTheDocument());
    expect(screen.getByTestId("analysis-full-report")).toHaveTextContent("正文全文");
    expect(screen.queryByText("EXCERPT-ONLY-SHORT")).toBeNull();

    // The running row opens a LIVE RunView (SSE subscribed).
    await user.click(screen.getByRole("button", { name: "View run" }));
    expect(screen.getByTestId("mock-run-view")).toHaveTextContent("run-live");
    expect(screen.getByTestId("mock-run-view")).toHaveTextContent("LIVE");
    await user.click(screen.getByRole("button", { name: "back" }));

    // Completed rows open a READ-ONLY RunView (no SSE, no cancel control).
    await user.click(screen.getByRole("button", { name: "View report" }));
    expect(screen.getByTestId("mock-run-view")).toHaveTextContent("run-h1");
    expect(screen.getByTestId("mock-run-view")).toHaveTextContent("READONLY");

    // Back returns to the tab and reloads history.
    await user.click(screen.getByRole("button", { name: "back" }));
    await waitFor(() =>
      expect(listWatchAnalyses).toHaveBeenLastCalledWith("600519.SH", {
        category: "technical",
        limit: 20,
      }),
    );
  });

  it("shows the empty-agents and empty-history states", async () => {
    listWatchAgents.mockResolvedValue({ items: [] });
    render(<AnalysisTab category="fundamental" symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByText("No published analysts in this category")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("analysis-history-empty")).toBeInTheDocument();
  });

  it("shows the advisory 412 Chanlun prompt; jump to update or skip & run", async () => {
    const user = userEvent.setup();
    const onGotoObjective = vi.fn();
    startWatchAnalysis.mockRejectedValueOnce(
      new ApiError(
        "缠论分析所需的各级别行情尚未齐备",
        412,
        "kline_not_ready",
        {
          items: [
            { interval: "1d", required: true, status: "not_fetched", fetch_failed: false },
            { interval: "1w", required: true, status: "failed", fetch_failed: false },
          ],
        },
      ),
    );
    render(
      <AnalysisTab
        category="technical"
        symbol="600519.SH"
        onGotoObjective={onGotoObjective}
      />,
    );
    await waitFor(() =>
      expect(screen.getByText(/Classic Technical Analyst/)).toBeInTheDocument(),
    );

    await user.selectOptions(screen.getByTestId("analysis-role-select"), CHANLUN_REF);
    await user.click(screen.getByTestId("analysis-run-btn"));

    const gate = await screen.findByTestId("chanlun-kline-gate");
    expect(gate).toBeInTheDocument();
    expect(screen.getByTestId("chanlun-gate-item-1d")).toHaveTextContent(/Not fetched/);
    expect(screen.getByTestId("chanlun-gate-item-1w")).toHaveTextContent(/Fetch failed/);

    // First choice: leave for the Objective-data tab; no run created.
    await user.click(screen.getByTestId("chanlun-gate-go"));
    expect(onGotoObjective).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("mock-run-view")).toBeNull();

    // Second choice: skip the prompt and the run starts (BDD rule 18).
    await user.click(screen.getByTestId("chanlun-gate-skip"));
    await waitFor(() => expect(startWatchAnalysis).toHaveBeenCalledTimes(2));
    expect(startWatchAnalysis).toHaveBeenLastCalledWith("600519.SH", {
      category: "technical",
      role_ref: "technical_analysis_panel:chanlun_analyst",
      skip_kline_gate: true,
    });
    expect(await screen.findByTestId("mock-run-view")).toHaveTextContent("run-new");
  });

  it("warns (without blocking) when the selected Chanlun role lacks 30m bars", async () => {
    const user = userEvent.setup();
    getWatchKlineStatus.mockResolvedValue({
      items: [
        { interval: "30m", required: false, status: "not_fetched", fetch_failed: false },
      ],
      market_ref: { last_trading_date: null, threshold_date: null, source: "weekday" },
    });
    render(<AnalysisTab category="technical" symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByText(/Classic Technical Analyst/)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("chanlun-30m-warn")).toBeNull();

    await user.selectOptions(screen.getByTestId("analysis-role-select"), CHANLUN_REF);
    await waitFor(() =>
      expect(screen.getByTestId("chanlun-30m-warn")).toBeInTheDocument(),
    );

    // A non-Chanlun selection clears the advisory warning.
    await user.selectOptions(screen.getByTestId("analysis-role-select"), CLASSIC_REF);
    await waitFor(() =>
      expect(screen.queryByTestId("chanlun-30m-warn")).toBeNull(),
    );
  });
});
