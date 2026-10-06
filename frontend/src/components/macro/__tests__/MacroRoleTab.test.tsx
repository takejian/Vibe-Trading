import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MacroRoleTab } from "../MacroRoleTab";
import type { RoleGroup } from "@/lib/api";

const listRoleGroups = vi.fn();
const getRoleDetail = vi.fn();
const createRoleRun = vi.fn();
const listRoleRuns = vi.fn();
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
      listRoleGroups: (...args: unknown[]) => listRoleGroups(...args),
      getRoleDetail: (...args: unknown[]) => getRoleDetail(...args),
      createRoleRun: (...args: unknown[]) => createRoleRun(...args),
      listRoleRuns: (...args: unknown[]) => listRoleRuns(...args),
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

import { resetMacroEvalCache } from "../macroEvalRecords";

const group = (
  ref: string,
  title: string,
  agents: [string, string][],
): RoleGroup => ({
  ref,
  title,
  roles: agents.map(([agentId, name]) => ({
    ref: `${ref}:${agentId}`,
    name,
    purpose: `${name} duty`,
    approved: true,
  })),
});

const GROUPS: RoleGroup[] = [
  group("macro_strategy_forum", "Macro Strategy Forum", [
    ["global_economist", "Global Economist"],
    ["domestic_economist", "China Economist"],
    ["policy_analyst", "Policy Analyst"],
    ["chief_strategist", "Chief Strategist"],
  ]),
  group("macro_rates_fx_desk", "Macro / Rates / FX Desk", [
    ["rates_analyst", "Global Rates & Yield Curve Analyst"],
    ["fx_strategist", "FX Strategist"],
    ["commodity_inflation_analyst", "Commodity & Inflation Analyst"],
    ["macro_pm", "Macro Portfolio Manager"],
  ]),
  group("geopolitical_war_room", "Geopolitical Risk War Room", [
    ["geopolitical_analyst", "Geopolitical Analyst"],
    ["energy_analyst", "Energy Shock Analyst"],
    ["supply_chain_analyst", "Supply Chain Analyst"],
    ["chief_strategist", "Chief Strategist"],
  ]),
  group("sector_rotation_team", "Sector Rotation Team", [
    ["cycle_analyst", "Economic Cycle Analyst"],
    ["prosperity_analyst", "Sector Prosperity Analyst"],
    ["flow_analyst", "Capital Flow Analyst"],
    ["rotation_strategist", "Sector Rotation Strategist"],
  ]),
  group("equity_research_team", "Equity Research Team", [
    ["macro_analyst", "Macro Analyst"],
  ]),
  group("etf_allocation_desk", "ETF Allocation Desk", [
    ["macro_allocator", "Macro Allocator"],
  ]),
];

const ALL_REFS = GROUPS.flatMap((g) => g.roles.map((item) => item.ref));

const ECONOMIST_PROFILE = {
  kind: "builtin" as const,
  ref: "macro_strategy_forum:global_economist",
  name: "Global Economist",
  purpose: "Tracks global monetary and growth cycles.",
  system_prompt: "prompt",
  tools: ["get_market_data"],
  skills: ["global-macro"],
  max_iterations: 20,
  timeout_seconds: 600,
  approved: true,
};

const roleRunSummary = (
  id: string,
  roleRef: string,
  target: string,
  excerpt: string,
) =>
  ({
    id,
    preset_name: roleRef.split(":")[0],
    status: "completed",
    created_at: "2026-10-12T00:00:00Z",
    completed_at: "2026-10-12T01:00:00Z",
    trial_role: roleRef,
    kind: "role_run",
    task_count: 1,
    completed_count: 1,
    research_target: target,
    research_question: "",
    final_report_excerpt: excerpt,
  });

const ROLE_RUN_RECORDS = [
  roleRunSummary(
    "role-run-a",
    "macro_strategy_forum:global_economist",
    "A-shares",
    "External demand drag is easing as global trade volumes post a second monthly gain.",
  ),
  roleRunSummary(
    "role-run-b",
    "macro_rates_fx_desk:rates_analyst",
    "CGB 10Y",
    "Yield curve steepening is expected to continue on widening term premia and heavy issuance.",
  ),
];

beforeEach(() => {
  vi.clearAllMocks();
  resetMacroEvalCache();
  listRoleGroups.mockResolvedValue({ groups: GROUPS });
  getRoleDetail.mockResolvedValue(ECONOMIST_PROFILE);
  listRoleRuns.mockResolvedValue([]);
  listSwarmRuns.mockResolvedValue([]);
  getSwarmRun.mockResolvedValue(null);
  createSession.mockResolvedValue({ session_id: "sess-role" });
  sendMessage.mockResolvedValue({ message_id: "msg-role", attempt_id: "att-1" });
});

describe("MacroRoleTab", () => {
  it("lists all 18 roles under seven themes", async () => {
    render(<MacroRoleTab />);

    const tab = await screen.findByTestId("macro-role-tab");
    expect(ALL_REFS).toHaveLength(18);
    for (const ref of ALL_REFS) {
      const safe = ref.replace(/[^A-Za-z0-9_-]/g, "-");
      expect(
        within(tab).getByTestId(`macro-role-item-${safe}`),
      ).toBeInTheDocument();
    }
    // Seven theme headings.
    expect(within(tab).getByText("Macro Economy & Cycle")).toBeInTheDocument();
    expect(within(tab).getByText("Rates & FX")).toBeInTheDocument();
    expect(
      within(tab).getByText("Commodities & Inflation"),
    ).toBeInTheDocument();
    expect(
      within(tab).getByText("Geopolitics & Supply Chain"),
    ).toBeInTheDocument();
    expect(within(tab).getByText("Policy Research")).toBeInTheDocument();
    expect(within(tab).getByText("Sector Rotation")).toBeInTheDocument();
    expect(
      within(tab).getByText("Strategy & Asset Allocation"),
    ).toBeInTheDocument();
  });

  it("loads a role profile, requires target and question, then launches a role run", async () => {
    const user = userEvent.setup();
    render(<MacroRoleTab />);

    await user.click(
      await screen.findByTestId(
        "macro-role-item-macro_strategy_forum-global_economist",
      ),
    );

    // Profile detail with source team renders (scope to the aside so the role
    // button label of the same name does not create multiple matches).
    const detailPanel = screen.getByTestId("macro-role-detail");
    expect(
      await within(detailPanel).findByText("Global Economist"),
    ).toBeInTheDocument();
    expect(
      within(detailPanel).getByText(/Source team: Macro Strategy Forum/),
    ).toBeInTheDocument();

    // Empty fields block the run.
    await user.click(screen.getByTestId("macro-role-run"));
    expect(await screen.findByTestId("macro-role-error")).toBeInTheDocument();
    expect(createRoleRun).not.toHaveBeenCalled();

    await user.type(screen.getByTestId("macro-role-target"), "  US Dollar Index  ");
    await user.type(
      screen.getByTestId("macro-role-question"),
      "Where is the dollar heading next quarter?",
    );
    createRoleRun.mockResolvedValue({
      id: "role-run-001",
      status: "pending",
      kind: "role",
    });
    await user.click(screen.getByTestId("macro-role-run"));

    await screen.findByTestId("run-view-mock");
    expect(createRoleRun).toHaveBeenCalledWith({
      role_ref: "macro_strategy_forum:global_economist",
      target: "US Dollar Index",
      question: "Where is the dollar heading next quarter?",
    });
  });

  it("lists standalone role-run records with search and row actions", async () => {
    const user = userEvent.setup();
    listRoleRuns.mockResolvedValue(ROLE_RUN_RECORDS);
    render(<MacroRoleTab />);

    const history = await screen.findByTestId("macro-role-history");
    expect(
      await within(history).findByTestId(
        "macro-role-history-row-role-run-a",
      ),
    ).toBeInTheDocument();
    expect(
      within(history).getByTestId("macro-role-history-row-role-run-b"),
    ).toBeInTheDocument();

    // Keyword search narrows rows.
    await user.type(
      within(history).getByTestId("macro-role-history-search-keyword"),
      "yield curve",
    );
    await user.click(
      within(history).getByTestId("macro-role-history-search-submit"),
    );
    expect(
      within(history).getByTestId("macro-role-history-row-role-run-b"),
    ).toBeInTheDocument();
    expect(
      within(history).queryByTestId("macro-role-history-row-role-run-a"),
    ).not.toBeInTheDocument();

    // View opens the run snapshot.
    await user.click(
      within(history).getByTestId("macro-role-history-view-role-run-b"),
    );
    expect(await screen.findByTestId("run-view-mock")).toHaveTextContent(
      "role-run-b",
    );
  });

  it("excludes non-macro role runs and auto-filters to the clicked role", async () => {
    const user = userEvent.setup();
    const nonMacroRecord = roleRunSummary(
      "role-run-c",
      "sales_ops_desk:sales_agent",
      "Sales quota",
      "This non-macro record must never appear in the macro role history.",
    );
    listRoleRuns.mockResolvedValue([...ROLE_RUN_RECORDS, nonMacroRecord]);
    render(<MacroRoleTab />);

    const history = await screen.findByTestId("macro-role-history");
    await within(history).findByTestId("macro-role-history-row-role-run-a");
    // Non-macro role run is excluded.
    expect(
      within(history).queryByTestId("macro-role-history-row-role-run-c"),
    ).not.toBeInTheDocument();

    // Clicking a role automatically filters the records to that role.
    await user.click(
      screen.getByTestId(
        "macro-role-item-macro_strategy_forum-global_economist",
      ),
    );
    const chip = await within(history).findByTestId(
      "macro-role-history-role-filter",
    );
    expect(chip).toHaveTextContent("Global Economist");
    expect(
      within(history).getByTestId("macro-role-history-row-role-run-a"),
    ).toBeInTheDocument();
    expect(
      within(history).queryByTestId("macro-role-history-row-role-run-b"),
    ).not.toBeInTheDocument();

    // Dismissing the chip restores all macro role records.
    await user.click(
      within(history).getByTestId("macro-role-history-role-filter-clear"),
    );
    expect(
      await within(history).findByTestId(
        "macro-role-history-row-role-run-b",
      ),
    ).toBeInTheDocument();
  });

  it("launches AI comparison for two checked role records", async () => {
    const user = userEvent.setup();
    listRoleRuns.mockResolvedValue(ROLE_RUN_RECORDS);
    render(<MacroRoleTab />);

    const history = await screen.findByTestId("macro-role-history");
    await within(history).findByTestId("macro-role-history-row-role-run-a");
    await user.click(
      within(history).getByTestId("macro-role-history-checkbox-role-run-a"),
    );
    await user.click(
      within(history).getByTestId("macro-role-history-checkbox-role-run-b"),
    );
    await user.click(
      within(history).getByTestId("macro-role-history-compare"),
    );

    await vi.waitFor(() =>
      expect(createSession).toHaveBeenCalledWith("Macro Evaluation Comparison"),
    );
    expect(sendMessage).toHaveBeenCalledTimes(1);
    const prompt = sendMessage.mock.calls[0][1] as string;
    expect(prompt.toLowerCase()).toContain("yield curve");
    expect(navigate).toHaveBeenCalledWith(
      expect.stringContaining("session=sess-role"),
    );
  });
});
