import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MacroTeamTab } from "../MacroTeamTab";
import { ApiError } from "@/lib/api";

const listSwarmPresets = vi.fn();
const getSwarmPresetDetail = vi.fn();
const createSwarmRun = vi.fn();
const listSwarmRuns = vi.fn();
const listRoleRuns = vi.fn();
const listRoleGroups = vi.fn();
const getSwarmRun = vi.fn();
const createSession = vi.fn();
const sendMessage = vi.fn();
const navigate = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listSwarmPresets: (...args: unknown[]) => listSwarmPresets(...args),
      getSwarmPresetDetail: (...args: unknown[]) => getSwarmPresetDetail(...args),
      createSwarmRun: (...args: unknown[]) => createSwarmRun(...args),
      listSwarmRuns: (...args: unknown[]) => listSwarmRuns(...args),
      listRoleRuns: (...args: unknown[]) => listRoleRuns(...args),
      listRoleGroups: (...args: unknown[]) => listRoleGroups(...args),
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

import { resetMacroEvalCache } from "../macroEvalRecords";

const PRESETS = [
  {
    name: "macro_strategy_forum",
    title: "Macro Strategy Forum",
    description: "Global + domestic + policy perspectives in parallel.",
    agent_count: 4,
    variables: [
      { name: "market", description: "Focus market", required: true },
      { name: "horizon", description: "Horizon", required: true },
    ],
  },
  {
    name: "macro_rates_fx_desk",
    title: "Macro / Rates / FX Desk",
    description: "Rates + FX + commodity desk.",
    agent_count: 4,
    variables: [],
  },
  {
    name: "geopolitical_war_room",
    title: "Geopolitical Risk War Room",
    description: "Geopolitics + energy + supply chain.",
    agent_count: 4,
    variables: [],
  },
  {
    name: "sector_rotation_team",
    title: "Sector Rotation Team",
    description: "Cycle + prosperity + flows.",
    agent_count: 4,
    variables: [],
  },
  // Preset outside the macro catalog must be ignored.
  {
    name: "crypto_trading_desk",
    title: "Crypto Trading Desk",
    description: "not macro",
    agent_count: 3,
    variables: [],
  },
];

const FORUM_DETAIL = {
  name: "macro_strategy_forum",
  title: "Macro Strategy Forum",
  description: "Global + domestic + policy perspectives in parallel.",
  variables: [
    { name: "market", description: "Focus market", required: true },
    { name: "horizon", description: "Horizon", required: true },
  ],
  agents: [
    { id: "global_economist", role: "Global Economist", skills: ["global-macro"] },
    { id: "domestic_economist", role: "China Economist", skills: [] },
    { id: "policy_analyst", role: "Policy Analyst", skills: [] },
    { id: "chief_strategist", role: "Chief Strategist", skills: [] },
  ],
  tasks: [],
  tool_catalog: ["read_url"],
  skill_catalog: ["global-macro"],
  layers: [],
};

const HISTORY_SUMMARY = {
  id: "team-run-9",
  preset_name: "macro_strategy_forum",
  status: "completed",
  created_at: "2026-10-11T00:00:00Z",
  completed_at: "2026-10-11T01:00:00Z",
  task_count: 2,
  completed_count: 2,
  research_target: "China 2026Q4",
  research_question: "cycle",
  kind: "team",
  final_report_excerpt: "",
} as const;

const HISTORY_DETAIL = {
  id: "team-run-9",
  preset_name: "macro_strategy_forum",
  status: "completed",
  created_at: "2026-10-11T00:00:00Z",
  completed_at: "2026-10-11T01:00:00Z",
  research_target: "China 2026Q4",
  research_question: "cycle",
  user_vars: {},
  agents: [],
  tasks: [
    {
      id: "task-a",
      agent_id: "global_economist",
      status: "completed",
      depends_on: [],
      input_from: [],
      summary:
        "Global leading indicators bottomed in October and credit impulse turned positive for a second month.",
      error: null,
      started_at: "2026-10-11T00:05:00Z",
      completed_at: "2026-10-11T00:40:00Z",
      worker_iterations: 2,
    },
    {
      id: "task-b",
      agent_id: "domestic_economist",
      status: "completed",
      depends_on: [],
      input_from: [],
      summary:
        "Domestic PMI rose to 50.4 and industrial profit margins improved, supporting the recovery call.",
      error: null,
      started_at: "2026-10-11T00:05:00Z",
      completed_at: "2026-10-11T00:42:00Z",
      worker_iterations: 2,
    },
  ],
  final_report:
    "The macro team concludes China is in an early recovery phase as credit impulse and PMI readings improved in October 2026.",
};

const OTHER_SUMMARY = {
  id: "team-run-10",
  preset_name: "macro_strategy_forum",
  status: "completed",
  created_at: "2026-10-12T00:00:00Z",
  completed_at: "2026-10-12T01:00:00Z",
  task_count: 1,
  completed_count: 1,
  research_target: "China policy outlook",
  research_question: "stimulus",
  kind: "team",
  final_report_excerpt: "",
} as const;

const OTHER_DETAIL = {
  id: "team-run-10",
  preset_name: "macro_strategy_forum",
  status: "completed",
  created_at: "2026-10-12T00:00:00Z",
  completed_at: "2026-10-12T01:00:00Z",
  research_target: "China policy outlook",
  research_question: "stimulus",
  user_vars: {},
  agents: [],
  tasks: [
    {
      id: "task-c",
      agent_id: "domestic_economist",
      status: "completed",
      depends_on: [],
      input_from: [],
      summary:
        "Fiscal stimulus is expected to broaden as local government issuance accelerates through year-end.",
      error: null,
      started_at: "2026-10-12T00:05:00Z",
      completed_at: "2026-10-12T00:40:00Z",
      worker_iterations: 2,
    },
  ],
  final_report:
    "The domestic view points to broadening fiscal support keeping the recovery on track into early 2027.",
};

const detailFor = (id: string) =>
  Promise.resolve(
    id === "team-run-9"
      ? HISTORY_DETAIL
      : id === "team-run-10"
        ? OTHER_DETAIL
        : null,
  );

beforeEach(() => {
  vi.clearAllMocks();
  resetMacroEvalCache();
  listSwarmPresets.mockResolvedValue(PRESETS);
  getSwarmPresetDetail.mockResolvedValue(FORUM_DETAIL);
  listSwarmRuns.mockResolvedValue([]);
  listRoleRuns.mockResolvedValue([]);
  listRoleGroups.mockResolvedValue({ groups: [] });
  getSwarmRun.mockImplementation(detailFor);
  createSession.mockResolvedValue({ session_id: "sess-history" });
  sendMessage.mockResolvedValue({ message_id: "msg-history", attempt_id: "att-1" });
});

describe("MacroTeamTab", () => {
  it("groups four teams under four themes and filters non-macro presets", async () => {
    render(<MacroTeamTab />);

    const tab = await screen.findByTestId("macro-team-tab");
    const cardIds = [
      "macro-team-card-macro_strategy_forum",
      "macro-team-card-macro_rates_fx_desk",
      "macro-team-card-geopolitical_war_room",
      "macro-team-card-sector_rotation_team",
    ];
    for (const id of cardIds) {
      expect(within(tab).getByTestId(id)).toBeInTheDocument();
    }
    expect(screen.queryByTestId("macro-team-card-crypto_trading_desk")).not.toBeInTheDocument();
  });

  it("expands a team, blocks launch with missing required vars, then launches with trimmed values", async () => {
    const user = userEvent.setup();
    render(<MacroTeamTab />);

    await user.click(await screen.findByTestId("macro-team-expand-macro_strategy_forum"));

    // Roles and parameter inputs render from the detail.
    expect(await screen.findByText("Global Economist")).toBeInTheDocument();
    const marketInput = screen.getByTestId("macro-team-var-macro_strategy_forum-market");
    const horizonInput = screen.getByTestId("macro-team-var-macro_strategy_forum-horizon");

    // Empty required fields: launch blocked, no run created.
    await user.click(screen.getByTestId("macro-team-launch-macro_strategy_forum"));
    expect(await screen.findByTestId("macro-team-error-macro_strategy_forum")).toBeInTheDocument();
    expect(createSwarmRun).not.toHaveBeenCalled();

    await user.type(marketInput, "  A-shares  ");
    await user.type(horizonInput, "quarterly");
    createSwarmRun.mockResolvedValue({ id: "swarm-001", status: "pending" });
    await user.click(screen.getByTestId("macro-team-launch-macro_strategy_forum"));

    await screen.findByTestId("run-view-mock");
    expect(createSwarmRun).toHaveBeenCalledWith("macro_strategy_forum", {
      market: "A-shares",
      horizon: "quarterly",
    });
  });

  it("surfaces an in-progress message when the server returns 409", async () => {
    const user = userEvent.setup();
    render(<MacroTeamTab />);

    await user.click(await screen.findByTestId("macro-team-expand-macro_strategy_forum"));
    await screen.findByText("Global Economist");
    await user.type(screen.getByTestId("macro-team-var-macro_strategy_forum-market"), "A");
    await user.type(screen.getByTestId("macro-team-var-macro_strategy_forum-horizon"), "Q");
    createSwarmRun.mockRejectedValue(new ApiError(409, "conflict", {}));
    await user.click(screen.getByTestId("macro-team-launch-macro_strategy_forum"));

    expect(await screen.findByTestId("macro-team-error-macro_strategy_forum")).toBeInTheDocument();
  });

  it("lists one row per team run and searches by target", async () => {
    const user = userEvent.setup();
    listSwarmRuns.mockResolvedValue([HISTORY_SUMMARY, OTHER_SUMMARY]);
    render(<MacroTeamTab />);

    const history = await screen.findByTestId("macro-team-history");
    expect(
      await within(history).findByTestId(
        "macro-team-history-row-team-run-9#run",
      ),
    ).toBeInTheDocument();
    expect(
      within(history).getByTestId("macro-team-history-row-team-run-10#run"),
    ).toBeInTheDocument();
    // No per-task rows: role/source columns are gone.
    expect(
      within(history).queryByTestId(
        "macro-team-history-row-team-run-9#task-a",
      ),
    ).not.toBeInTheDocument();

    await user.type(
      within(history).getByTestId("macro-team-history-search-keyword"),
      "China 2026Q4",
    );
    await user.click(
      within(history).getByTestId("macro-team-history-search-submit"),
    );
    expect(
      within(history).getByTestId("macro-team-history-row-team-run-9#run"),
    ).toBeInTheDocument();
    expect(
      within(history).queryByTestId(
        "macro-team-history-row-team-run-10#run",
      ),
    ).not.toBeInTheDocument();
  });

  it("ignores team runs whose preset is outside the macro catalog", async () => {
    const nonMacroSummary = {
      ...HISTORY_SUMMARY,
      id: "crypto-run-1",
      preset_name: "crypto_trading_desk",
    };
    const nonMacroDetail = {
      ...HISTORY_DETAIL,
      id: "crypto-run-1",
      preset_name: "crypto_trading_desk",
    };
    listSwarmRuns.mockResolvedValue([HISTORY_SUMMARY, nonMacroSummary]);
    getSwarmRun.mockImplementation((id: string) =>
      Promise.resolve(id === "team-run-9" ? HISTORY_DETAIL : nonMacroDetail),
    );
    render(<MacroTeamTab />);

    const history = await screen.findByTestId("macro-team-history");
    await within(history).findByTestId(
      "macro-team-history-row-team-run-9#run",
    );
    expect(
      within(history).queryByTestId(
        "macro-team-history-row-crypto-run-1#run",
      ),
    ).not.toBeInTheDocument();
  });

  it("filters the run rows to the clicked agent and restores on chip clear", async () => {
    const user = userEvent.setup();
    listSwarmRuns.mockResolvedValue([HISTORY_SUMMARY, OTHER_SUMMARY]);
    render(<MacroTeamTab />);

    // Expand the forum and click one agent.
    await user.click(
      await screen.findByTestId("macro-team-expand-macro_strategy_forum"),
    );
    await user.click(
      screen.getByTestId(
        "macro-team-agent-macro_strategy_forum-global_economist",
      ),
    );

    const history = screen.getByTestId("macro-team-history");
    const chip = await within(history).findByTestId(
      "macro-team-history-role-filter",
    );
    expect(chip).toHaveTextContent("Global Economist");
    // Only the run with a global_economist task remains.
    expect(
      within(history).getByTestId("macro-team-history-row-team-run-9#run"),
    ).toBeInTheDocument();
    expect(
      within(history).queryByTestId(
        "macro-team-history-row-team-run-10#run",
      ),
    ).not.toBeInTheDocument();

    // Clearing the chip restores every macro team run.
    await user.click(
      within(history).getByTestId("macro-team-history-role-filter-clear"),
    );
    expect(
      await within(history).findByTestId(
        "macro-team-history-row-team-run-10#run",
      ),
    ).toBeInTheDocument();
  });

  it("compares two checked team runs in a new AI session", async () => {
    const user = userEvent.setup();
    listSwarmRuns.mockResolvedValue([HISTORY_SUMMARY, OTHER_SUMMARY]);
    render(<MacroTeamTab />);

    const hist = await screen.findByTestId("macro-team-history");
    await within(hist).findByTestId(
      "macro-team-history-row-team-run-9#run",
    );
    await user.click(
      within(hist).getByTestId(
        "macro-team-history-checkbox-team-run-9#run",
      ),
    );
    await user.click(
      within(hist).getByTestId(
        "macro-team-history-checkbox-team-run-10#run",
      ),
    );
    expect(
      within(hist).getByTestId("macro-team-history-selected-count"),
    ).toHaveTextContent("2 selected");

    await user.click(within(hist).getByTestId("macro-team-history-compare"));

    await vi.waitFor(() =>
      expect(createSession).toHaveBeenCalledWith("Macro Evaluation Comparison"),
    );
    expect(sendMessage).toHaveBeenCalledTimes(1);
    const prompt = sendMessage.mock.calls[0][1] as string;
    expect(prompt).toContain("China 2026Q4");
    expect(prompt).toContain("China policy outlook");
    expect(navigate).toHaveBeenCalledWith(
      expect.stringContaining("session=sess-history"),
    );
  });
});
