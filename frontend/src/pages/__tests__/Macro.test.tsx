import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { Macro } from "../Macro";
import { resetMacroEvalCache } from "@/components/macro/macroEvalRecords";

const PROMPTS = [
  {
    code: "a",
    name: "宏观经济周期判定",
    prompt_text: "系统提示词正文",
    enabled: true,
    sort_order: 1,
    editable: true,
    can_edit: true,
    orchestration_config: null,
    update_time: null,
  },
  {
    code: "b",
    name: "待扩展（敬请期待）",
    prompt_text: "预留",
    enabled: false,
    sort_order: 2,
    editable: false,
    can_edit: false,
    orchestration_config: null,
    update_time: null,
  },
  {
    code: "c",
    name: "待扩展（敬请期待）",
    prompt_text: "预留",
    enabled: false,
    sort_order: 3,
    editable: false,
    can_edit: false,
    orchestration_config: null,
    update_time: null,
  },
];

const JUDGMENT = {
  id: 1,
  economy: "中国",
  statistics_date: "2026-08",
  current_cycle: "复苏期",
  judgment_result: "复苏期。",
  dimension_check: "增长回升。",
  meso_verify: "库存去化。",
  history_cycle_anchor: "类似 2016。",
  judgment_confidence: "中",
  core_support: "信贷。",
  core_risk: "外需。",
  extended_remark: "",
  create_time: null,
};

const listMacroPrompts = vi.fn();
const listMacroEconomies = vi.fn();
const listMacroJudgments = vi.fn();
const updateMacroPrompt = vi.fn();
const listSwarmPresets = vi.fn();
const listRoleGroups = vi.fn();
const listRoleRuns = vi.fn();
const listSwarmRuns = vi.fn();
const getSwarmRun = vi.fn();
const navigate = vi.fn();

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>(
    "react-router",
  );
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listMacroPrompts: (...args: unknown[]) => listMacroPrompts(...args),
      listMacroEconomies: (...args: unknown[]) => listMacroEconomies(...args),
      listMacroJudgments: (...args: unknown[]) => listMacroJudgments(...args),
      updateMacroPrompt: (...args: unknown[]) => updateMacroPrompt(...args),
      listSwarmPresets: (...args: unknown[]) => listSwarmPresets(...args),
      listRoleGroups: (...args: unknown[]) => listRoleGroups(...args),
      listRoleRuns: (...args: unknown[]) => listRoleRuns(...args),
      listSwarmRuns: (...args: unknown[]) => listSwarmRuns(...args),
      getSwarmRun: (...args: unknown[]) => getSwarmRun(...args),
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  resetMacroEvalCache();
  listMacroPrompts.mockResolvedValue({ status: "ok", prompts: PROMPTS });
  listMacroEconomies.mockResolvedValue({
    status: "ok",
    economies: ["中国", "美国", "日本", "欧元区"],
  });
  listMacroJudgments.mockResolvedValue({
    status: "ok",
    economy: "中国",
    judgments: [JUDGMENT, { ...JUDGMENT, statistics_date: "2026-07" }],
  });
  updateMacroPrompt.mockResolvedValue({ status: "ok", prompt: PROMPTS[0] });
  listSwarmPresets.mockResolvedValue([
    {
      name: "macro_strategy_forum",
      title: "Macro Strategy Forum",
      description: "",
      agent_count: 4,
      variables: [],
    },
  ]);
  listRoleGroups.mockResolvedValue({ groups: [] });
  listRoleRuns.mockResolvedValue([]);
  listSwarmRuns.mockResolvedValue([]);
  getSwarmRun.mockResolvedValue(null);
});

describe("Macro page", () => {
  it("lists prompts a/b/c, marks b and c reserved, and edits only prompt a", async () => {
    const user = userEvent.setup();
    render(<Macro />);

    const page = await screen.findByTestId("macro-page");
    expect(within(page).getByTestId("macro-prompt-card-a")).toBeInTheDocument();
    expect(within(page).getByTestId("macro-prompt-card-b")).toBeInTheDocument();
    expect(within(page).getByTestId("macro-prompt-card-c")).toBeInTheDocument();

    // b/c are explicitly marked as coming soon.
    expect(screen.getAllByText("Coming soon").length).toBeGreaterThanOrEqual(2);

    // Open the editor for a, change the body, save.
    await user.click(screen.getByTestId("macro-edit-prompt-a"));
    const textarea = screen.getByTestId("macro-prompt-textarea");
    expect(textarea).toHaveValue("系统提示词正文");
    await user.clear(textarea);
    await user.type(textarea, "新的提示词正文");
    await user.click(screen.getByTestId("macro-prompt-save"));

    await vi.waitFor(() =>
      expect(updateMacroPrompt).toHaveBeenCalledWith("a", "新的提示词正文"),
    );
  });

  it("disables the edit entry when the principal lacks settings-write rights", async () => {
    listMacroPrompts.mockResolvedValue({
      status: "ok",
      prompts: [{ ...PROMPTS[0], can_edit: false }, PROMPTS[1], PROMPTS[2]],
    });
    render(<Macro />);

    const editButton = await screen.findByTestId("macro-edit-prompt-a");
    expect(editButton).toBeDisabled();
  });

  it("loads descending history for the selected economy and opens a month detail", async () => {
    const user = userEvent.setup();
    render(<Macro />);

    await screen.findByTestId("macro-page");
    const months = await screen.findByText("2026-08");
    expect(months).toBeInTheDocument();
    expect(screen.getByText("2026-07")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "2026-08" }));
    const detail = await screen.findByTestId("macro-judgment-detail");
    expect(within(detail).getByText("中国")).toBeInTheDocument();
    expect(listMacroJudgments).toHaveBeenCalledWith("中国");

    // Switching economy re-queries the timeline.
    await user.selectOptions(screen.getByTestId("macro-history-economy"), "美国");
    await vi.waitFor(() => expect(listMacroJudgments).toHaveBeenLastCalledWith("美国"));
  });

  it("keeps the orchestration entry purely informational (no write request)", async () => {
    const user = userEvent.setup();
    render(<Macro />);

    await screen.findByTestId("macro-page");
    const entry = screen.getByTestId("macro-orchestration-entry");
    expect(screen.queryByTestId("macro-orchestration-note")).not.toBeInTheDocument();
    await user.click(entry);
    expect(screen.getByTestId("macro-orchestration-note")).toBeInTheDocument();

    // Only read calls happened; the reserved entry triggers nothing.
    expect(updateMacroPrompt).not.toHaveBeenCalled();
  });

  it("defaults to the cycle tab and lazily mounts the team and role tabs", async () => {
    const user = userEvent.setup();
    render(<Macro />);

    await screen.findByTestId("macro-page");
    const cyclePanel = screen.getByTestId("macro-panel-cycle");
    expect(cyclePanel).not.toHaveAttribute("hidden");
    // Team/role panels are not mounted before first activation.
    expect(screen.queryByTestId("macro-panel-team")).not.toBeInTheDocument();
    expect(screen.queryByTestId("macro-panel-role")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("macro-tab-team"));
    const teamPanel = await screen.findByTestId("macro-panel-team");
    expect(teamPanel).not.toHaveAttribute("hidden");
    expect(within(teamPanel).getByTestId("macro-team-tab")).toBeInTheDocument();
    expect(cyclePanel).toHaveAttribute("hidden");

    await user.click(screen.getByTestId("macro-tab-role"));
    const rolePanel = await screen.findByTestId("macro-panel-role");
    expect(rolePanel).not.toHaveAttribute("hidden");
    expect(teamPanel).toHaveAttribute("hidden");

    // Switching back keeps previously mounted panels in the DOM (state kept alive).
    await user.click(screen.getByTestId("macro-tab-cycle"));
    expect(cyclePanel).not.toHaveAttribute("hidden");
    expect(teamPanel).toHaveAttribute("hidden");
    expect(rolePanel).toHaveAttribute("hidden");
  });
  it("lazily mounts the indicator board tab", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Macro />
      </MemoryRouter>,
    );

    await screen.findByTestId("macro-page");
    expect(screen.queryByTestId("macro-panel-board")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("macro-tab-board"));
    const boardPanel = await screen.findByTestId("macro-panel-board");
    expect(boardPanel).not.toHaveAttribute("hidden");
    expect(
      within(boardPanel).getByTestId("macro-board-tab"),
    ).toBeInTheDocument();
    expect(listRoleRuns).toHaveBeenCalledWith({ limit: 100 });

    // Returning to the cycle tab keeps the board mounted but hidden.
    await user.click(screen.getByTestId("macro-tab-cycle"));
    expect(screen.getByTestId("macro-panel-cycle")).not.toHaveAttribute("hidden");
    expect(boardPanel).toHaveAttribute("hidden");
  });
});
