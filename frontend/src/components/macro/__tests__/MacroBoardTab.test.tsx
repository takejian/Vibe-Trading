import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MacroBoardTab } from "../MacroBoardTab";
import type {
  RoleGroup,
  SwarmRunDetail,
  SwarmRunSummary,
} from "@/lib/api";
import { resetMacroEvalCache } from "../macroEvalRecords";

const listRoleRuns = vi.fn();
const listRoleGroups = vi.fn();
const listSwarmRuns = vi.fn();
const getSwarmRun = vi.fn();
const createSession = vi.fn();
const sendMessage = vi.fn();
const navigate = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listRoleRuns: (...args: unknown[]) => listRoleRuns(...args),
      listRoleGroups: (...args: unknown[]) => listRoleGroups(...args),
      listSwarmRuns: (...args: unknown[]) => listSwarmRuns(...args),
      getSwarmRun: (...args: unknown[]) => getSwarmRun(...args),
      createSession: (...args: unknown[]) => createSession(...args),
      sendMessage: (...args: unknown[]) => sendMessage(...args),
    },
  };
});

vi.mock("react-router", () => ({
  useNavigate: () => navigate,
}));

vi.mock("@/components/swarm/RunView", () => ({
  RunView: ({ runId }: { runId: string }) => (
    <div data-testid="run-view-mock">{runId}</div>
  ),
}));

const GROUPS: RoleGroup[] = [
  {
    ref: "etf_allocation_desk",
    title: "ETF Allocation Desk",
    roles: [
      { ref: "etf_allocation_desk:macro_allocator", name: "Macro Allocator", purpose: "ETF allocation", approved: true },
    ],
  },
  {
    ref: "equity_research_team",
    title: "Equity Research Team",
    roles: [
      { ref: "equity_research_team:macro_analyst", name: "Macro Analyst", purpose: "Macro equity view", approved: true },
    ],
  },
  {
    ref: "macro_strategy_forum",
    title: "Macro Strategy Forum",
    roles: [
      { ref: "macro_strategy_forum:global_economist", name: "Global Economist", purpose: "Global cycle", approved: true },
      { ref: "macro_strategy_forum:domestic_economist", name: "China Economist", purpose: "Domestic cycle", approved: true },
      { ref: "macro_strategy_forum:policy_analyst", name: "Policy Analyst", purpose: "Policy stance", approved: true },
    ],
  },
  {
    ref: "macro_rates_fx_desk",
    title: "Macro / Rates / FX Desk",
    roles: [
      { ref: "macro_rates_fx_desk:rates_analyst", name: "Global Rates Analyst", purpose: "Yield curve", approved: true },
      { ref: "macro_rates_fx_desk:fx_strategist", name: "FX Strategist", purpose: "Currencies", approved: true },
      { ref: "macro_rates_fx_desk:commodity_inflation_analyst", name: "Commodity & Inflation Analyst", purpose: "Inflation", approved: true },
    ],
  },
  {
    ref: "geopolitical_war_room",
    title: "Geopolitical Risk War Room",
    roles: [
      { ref: "geopolitical_war_room:energy_analyst", name: "Energy Shock Analyst", purpose: "Energy", approved: true },
      { ref: "geopolitical_war_room:geopolitical_analyst", name: "Geopolitical Analyst", purpose: "Geopolitics", approved: true },
    ],
  },
  {
    ref: "sector_rotation_team",
    title: "Sector Rotation Team",
    roles: [
      { ref: "sector_rotation_team:cycle_analyst", name: "Economic Cycle Analyst", purpose: "Inventory cycle", approved: true },
    ],
  },
];

const run = (
  id: string,
  roleRef: string,
  status: SwarmRunSummary["status"],
  target: string,
  createdAt: string,
  excerpt: string,
): SwarmRunSummary =>
  ({
    id,
    preset_name: roleRef.split(":")[0],
    status,
    created_at: createdAt,
    completed_at: status === "completed" ? createdAt : undefined,
    trial_role: roleRef,
    kind: "role_run",
    research_target: target,
    task_count: 3,
    completed_count: status === "completed" ? 3 : 1,
    final_report_excerpt: excerpt,
  }) as SwarmRunSummary;

const C1 = "Global manufacturing PMI rebounded to 50.6 in October, suggesting the industrial cycle is bottoming out across major economies.";
const C3 = "Trade volumes improved sequentially for a second month, consistent with an easing drag from weak external demand.";
const C5 = "Earlier PMI readings below 49 confirm the downcycle that preceded the current tentative stabilisation.";
const C2 = "The US 10-year Treasury yield held above 4.2 percent, sustaining curve steepening pressure through the quarter.";
const C6 = "The dollar index stalled at its 200-day average, reducing headwinds for emerging-market currencies.";
const C7 = "Brent crude held in a tight range, offering no fresh impulse to imported inflation this month.";

const C8 = "Credit impulse turned positive in October as new bank loans accelerated, signalling domestic demand is finding a floor.";

const TEAM_RUN_SUMMARY = {
  id: "team-run-1",
  preset_name: "macro_strategy_forum",
  status: "completed",
  created_at: "2026-10-10T00:00:00Z",
  completed_at: "2026-10-10T01:00:00Z",
  task_count: 1,
  completed_count: 1,
  research_target: "A-shares",
  research_question: "Q4 cycle",
  kind: "team",
  final_report_excerpt: "",
} as SwarmRunSummary;

const TEAM_RUN_DETAIL = {
  id: "team-run-1",
  preset_name: "macro_strategy_forum",
  status: "completed",
  created_at: "2026-10-10T00:00:00Z",
  completed_at: "2026-10-10T01:00:00Z",
  research_target: "A-shares",
  research_question: "Q4 cycle",
  user_vars: {},
  agents: [],
  tasks: [
    {
      id: "task-1",
      agent_id: "global_economist",
      status: "completed",
      depends_on: [],
      input_from: [],
      summary: C8,
      error: null,
      started_at: "2026-10-10T00:05:00Z",
      completed_at: "2026-10-10T00:45:00Z",
      worker_iterations: 2,
    },
  ],
  final_report: "synthesised report",
} as SwarmRunDetail;

const RUNS: SwarmRunSummary[] = [
  run("run-1", "macro_strategy_forum:global_economist", "completed", "A-shares", "2026-10-08T12:00:00Z", C1),
  run("run-2", "macro_rates_fx_desk:rates_analyst", "completed", "US Treasuries", "2026-10-07T09:30:00Z", C2),
  run("run-3", "macro_strategy_forum:global_economist", "completed", "Global equities", "2026-09-20T08:00:00Z", C3),
  run("run-4", "macro_strategy_forum:global_economist", "running", "A-shares", "2026-10-09T07:00:00Z", ""),
  run("run-5", "macro_strategy_forum:global_economist", "completed", "Global equities", "2026-08-01T08:00:00Z", C5),
  run("run-6", "macro_rates_fx_desk:fx_strategist", "completed", "Dollar index", "2026-10-06T10:00:00Z", C6),
  run("run-7", "macro_rates_fx_desk:commodity_inflation_analyst", "completed", "Brent crude", "2026-10-05T10:00:00Z", C7),
];

beforeEach(() => {
  vi.clearAllMocks();
  resetMacroEvalCache();
  listRoleRuns.mockResolvedValue(RUNS);
  listRoleGroups.mockResolvedValue({ groups: GROUPS });
  listSwarmRuns.mockResolvedValue([]);
  getSwarmRun.mockResolvedValue(TEAM_RUN_DETAIL);
  createSession.mockResolvedValue({ session_id: "sess-9" });
  sendMessage.mockResolvedValue({ message_id: "msg-1", attempt_id: "att-1" });
});

describe("MacroBoardTab", () => {
  it("renders five categories and eleven tracked-role cards", async () => {
    const { container } = render(<MacroBoardTab />);

    await screen.findByTestId("macro-board-tab");

    for (const category of [
      "Growth & Cycle",
      "Inflation & Commodities",
      "Money & Rates",
      "External & Geopolitical Risk",
      "Allocation & Equity Synthesis",
    ]) {
      expect(screen.getByText(category)).toBeInTheDocument();
    }

    for (const indicator of [
      "Global Manufacturing PMI",
      "Domestic PMI / Industrial Output",
      "Inventory & Capacity Cycle",
      "CPI / PPI",
      "Energy & Commodities",
      "Rates & Yield Curve",
      "Policy Rate / Social Financing & M2",
      "FX",
      "Geopolitics & Supply Chain",
      "Macro Allocator",
      "Macro Analyst",
    ]) {
      // These two indicator names equal their role names; allow both matches.
      expect(screen.getAllByText(indicator).length).toBeGreaterThanOrEqual(1);
    }

    expect(
      container.querySelectorAll('[data-testid^="macro-board-indicator-"]'),
    ).toHaveLength(11);

    // Six indicators have no completed evaluation yet.
    expect(
      screen.getAllByText(
        'No role evaluation for this indicator yet. Launch one from the "Macro Roles" tab.',
      ),
    ).toHaveLength(7);

    // The running evaluation shows a badge on the PMI indicator.
    const badge = await screen.findByTestId(
      "macro-board-running-macro_strategy_forum-global_economist",
    );
    expect(within(badge).getByText("Running")).toBeInTheDocument();
  });

  it("shows opening conclusions for the latest two runs and expands to all", async () => {
    const user = userEvent.setup();
    render(<MacroBoardTab />);

    await screen.findByTestId("macro-board-tab");

    expect(screen.getByText(C1)).toBeInTheDocument();
    expect(screen.getByText(C3)).toBeInTheDocument();
    expect(screen.getByText("A-shares · 2026-10-08")).toBeInTheDocument();

    // Third run is collapsed.
    expect(screen.queryByText(C5)).not.toBeInTheDocument();

    const expand = screen.getByTestId(
      "macro-board-expand-macro_strategy_forum-global_economist",
    );
    expect(expand).toHaveTextContent("Show all 3");
    await user.click(expand);

    expect(screen.getByText(C5)).toBeInTheDocument();
    expect(expand).toHaveTextContent("Collapse");
  });

  it("opens the full role report", async () => {
    const user = userEvent.setup();
    render(<MacroBoardTab />);

    await screen.findByTestId("macro-board-tab");
    await user.click(screen.getByTestId("macro-board-view-run-1"));

    const view = await screen.findByTestId("run-view-mock");
    expect(view).toHaveTextContent("run-1");
  });

  it("tracks the selection count and launches an AI comparison session", async () => {
    const user = userEvent.setup();
    render(<MacroBoardTab />);

    await screen.findByTestId("macro-board-tab");

    await user.click(screen.getByTestId("macro-board-run-checkbox-run-1"));
    await user.click(screen.getByTestId("macro-board-run-checkbox-run-2"));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    await user.click(screen.getByTestId("macro-board-compare"));

    await vi.waitFor(() =>
      expect(createSession).toHaveBeenCalledWith("Macro Indicator Comparison"),
    );
    expect(sendMessage).toHaveBeenCalledTimes(1);
    const prompt = sendMessage.mock.calls[0][1] as string;
    expect(prompt).toContain("Global Manufacturing PMI");
    expect(prompt).toContain("Rates & Yield Curve");
    expect(prompt).toContain(C1);
    expect(prompt).toContain(C2);
    expect(sendMessage.mock.calls[0][0]).toBe("sess-9");
    expect(navigate).toHaveBeenCalledWith("/agent?session=sess-9");
  });

  it("refuses comparison with fewer than two evaluations", async () => {
    const user = userEvent.setup();
    render(<MacroBoardTab />);

    await screen.findByTestId("macro-board-tab");
    const compareBtn = screen.getByTestId("macro-board-compare");
    expect(compareBtn).toBeDisabled();

    await user.click(screen.getByTestId("macro-board-run-checkbox-run-1"));
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(compareBtn).toBeDisabled();

    // The button is disabled by design; invoke its onClick closure to
    // exercise the defensive guard branch directly.
    const propsKey = Object.keys(compareBtn).find((k) =>
      k.startsWith("__reactProps$"),
    );
    expect(propsKey).toBeTruthy();
    (compareBtn as unknown as Record<string, { onClick: () => void }>)[
      propsKey as string
    ].onClick();

    const error = await screen.findByTestId("macro-board-compare-error");
    expect(error).toHaveTextContent("Check at least 2 evaluations to compare.");
    expect(createSession).not.toHaveBeenCalled();
  });

  it("caps selection at five evaluations", async () => {
    const user = userEvent.setup();
    render(<MacroBoardTab />);

    await screen.findByTestId("macro-board-tab");
    await user.click(
      screen.getByTestId(
        "macro-board-expand-macro_strategy_forum-global_economist",
      ),
    );

    for (const id of ["run-1", "run-3", "run-5", "run-2", "run-6"]) {
      await user.click(screen.getByTestId(`macro-board-run-checkbox-${id}`));
    }
    expect(screen.getByText("5 selected")).toBeInTheDocument();

    const sixth = screen.getByTestId("macro-board-run-checkbox-run-7");
    expect(sixth).toBeDisabled();
    expect(sixth).toHaveAttribute(
      "title",
      "Up to 5 evaluations can be compared at once.",
    );
  });

  it("shows an error when evaluations cannot be loaded", async () => {
    listRoleRuns.mockRejectedValueOnce(new Error("network down"));
    render(<MacroBoardTab />);

    expect(
      await screen.findByTestId("macro-board-load-error"),
    ).toBeInTheDocument();
  });

  it("syncs completed team-run tasks onto the tracked role cards", async () => {
    const user = userEvent.setup();
    listSwarmRuns.mockResolvedValue([TEAM_RUN_SUMMARY]);
    render(<MacroBoardTab />);

    await screen.findByTestId("macro-board-tab");
    expect(await screen.findByText(C8)).toBeInTheDocument();

    // The team task is attributable to the team run; viewing opens its snapshot.
    await user.click(
      screen.getByTestId("macro-board-view-team-run-1#task-1"),
    );
    const view = await screen.findByTestId("run-view-mock");
    expect(view).toHaveTextContent("team-run-1");
  });

  it("filters board records by the global keyword search", async () => {
    const user = userEvent.setup();
    listSwarmRuns.mockResolvedValue([TEAM_RUN_SUMMARY]);
    render(<MacroBoardTab />);

    await screen.findByTestId("macro-board-tab");
    await screen.findByText(C8);

    await user.type(
      screen.getByTestId("macro-board-search-input"),
      "Credit impulse",
    );
    await user.click(screen.getByTestId("macro-board-search-submit"));

    const count = await screen.findByTestId("macro-board-search-count");
    expect(count).toHaveTextContent("1 matching record");
    expect(screen.getByText(C8)).toBeInTheDocument();
    expect(screen.queryByText(C1)).not.toBeInTheDocument();

    // Clearing restores the full board.
    await user.click(screen.getByTestId("macro-board-search-clear"));
    expect(screen.getByText(C1)).toBeInTheDocument();
  });
});
