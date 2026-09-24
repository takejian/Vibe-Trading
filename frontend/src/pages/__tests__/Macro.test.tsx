import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Macro } from "../Macro";

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

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listMacroPrompts: (...args: unknown[]) => listMacroPrompts(...args),
      listMacroEconomies: (...args: unknown[]) => listMacroEconomies(...args),
      listMacroJudgments: (...args: unknown[]) => listMacroJudgments(...args),
      updateMacroPrompt: (...args: unknown[]) => updateMacroPrompt(...args),
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
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
});
