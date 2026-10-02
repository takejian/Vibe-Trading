import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AnalysisTab } from "../AnalysisTab";

const listWatchAgents = vi.fn();
const listWatchAnalyses = vi.fn();
const startWatchAnalysis = vi.fn();
const runViewSpy = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listWatchAgents: (...args: unknown[]) => listWatchAgents(...args),
      listWatchAnalyses: (...args: unknown[]) => listWatchAnalyses(...args),
      startWatchAnalysis: (...args: unknown[]) => startWatchAnalysis(...args),
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

const AGENTS = {
  items: [
    {
      ref: "technical_analysis_panel:chanlun_analyst",
      name: "Chanlun (Chan Theory) Analyst",
      purpose: "中枢背驰买卖点",
      category: "technical" as const,
      is_chanlun: true,
    },
    {
      ref: "technical_analysis_panel:classic_ta_analyst",
      name: "Classic Technical Analyst",
      purpose: "均线 MACD",
      category: "technical" as const,
      is_chanlun: false,
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
    listWatchAgents.mockResolvedValue(AGENTS);
    listWatchAnalyses.mockResolvedValue({ items: [] });
    startWatchAnalysis.mockResolvedValue({
      id: "run-new",
      status: "pending",
      kind: "role_run",
      trial_role: AGENTS.items[0].ref,
    });
  });

  it("requests the given category catalog and disables run until a role is chosen", async () => {
    render(
      <AnalysisTab category="technical" symbol="600519.SH" symbolName="贵州茅台" />,
    );
    await waitFor(() =>
      expect(screen.getByText("Classic Technical Analyst")).toBeInTheDocument(),
    );
    expect(listWatchAgents).toHaveBeenCalledWith("technical");
    expect(screen.getByTestId("analysis-run-btn")).toBeDisabled();
    expect(screen.getByText("Select exactly one analyst to start")).toBeInTheDocument();
    // Chanlun role carries a visual marker.
    expect(screen.getByTestId("chanlun-badge")).toHaveTextContent("Chanlun");
  });

  it("starts an analysis with the selected role; question omitted when empty", async () => {
    const user = userEvent.setup();
    render(<AnalysisTab category="technical" symbol="600519.SH" />);
    await screen.findByText("Classic Technical Analyst");

    await user.click(screen.getByRole("radio", { name: /Classic Technical/ }));
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
        },
      ],
    });
    render(<AnalysisTab category="general" symbol="000001.SZ" />);
    await waitFor(() => expect(listWatchAgents).toHaveBeenCalledWith("general"));
    await screen.findByText("Generalist");
    await user.click(screen.getByRole("radio", { name: "Generalist" }));
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
    await screen.findByText("Classic Technical Analyst");

    await user.click(screen.getByRole("radio", { name: /Classic Technical/ }));
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
});
