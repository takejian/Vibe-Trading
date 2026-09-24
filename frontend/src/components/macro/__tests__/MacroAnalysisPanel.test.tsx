import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MacroAnalysisPanel } from "../MacroAnalysisPanel";
import { ApiError } from "@/lib/api";

const JUDGMENT = {
  id: 1,
  economy: "中国",
  statistics_date: "2026-08",
  current_cycle: "复苏期，内需修复。",
  judgment_result: "判定为复苏期。",
  dimension_check: "增长回升、通胀温和。",
  meso_verify: "库存周期与产能周期共振向上。",
  history_cycle_anchor: "类似 2016 年供给侧阶段。",
  judgment_confidence: "中（样本有限）",
  core_support: "社融与信贷扩张。",
  core_risk: "外需与地产仍有背离风险。",
  extended_remark: "部分高频数据缺失。",
  create_time: null,
};

const listMacroEconomies = vi.fn();
const runMacroCycleJudgment = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listMacroEconomies: (...args: unknown[]) => listMacroEconomies(...args),
      runMacroCycleJudgment: (...args: unknown[]) => runMacroCycleJudgment(...args),
    },
  };
});

function setup() {
  listMacroEconomies.mockResolvedValue({
    status: "ok",
    economies: ["中国", "美国", "日本", "欧元区"],
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  setup();
});

describe("MacroAnalysisPanel", () => {
  it("renders a successful judgment with conclusion header and six sections", async () => {
    runMacroCycleJudgment.mockResolvedValue({
      status: "ok",
      cached: false,
      judgment: JUDGMENT,
    });
    render(<MacroAnalysisPanel />);

    const runButton = await screen.findByTestId("macro-run-button");
    await userEvent.click(runButton);

    const detail = await screen.findByTestId("macro-judgment-detail");
    expect(within(detail).getByText("中国")).toBeInTheDocument();
    expect(within(detail).getByText("2026-08")).toBeInTheDocument();
    expect(within(detail).getByText(/复苏期，内需修复/)).toBeInTheDocument();
    expect(screen.queryByTestId("macro-cached-badge")).not.toBeInTheDocument();
    // Six fixed sections.
    expect(within(detail).getByText("Judgment")).toBeInTheDocument();
    expect(within(detail).getByText("Dimension Check")).toBeInTheDocument();
    expect(within(detail).getByText("Meso Verification")).toBeInTheDocument();
    expect(within(detail).getByText("Historical Cycle Anchor")).toBeInTheDocument();
    expect(within(detail).getByText("Core Supports")).toBeInTheDocument();
    expect(within(detail).getByText("Core Risks")).toBeInTheDocument();
    expect(runMacroCycleJudgment).toHaveBeenCalledWith({ economy: "中国" });
  });

  it("marks cached results and explains no new model call was made", async () => {
    runMacroCycleJudgment.mockResolvedValue({
      status: "ok",
      cached: true,
      judgment: JUDGMENT,
    });
    render(<MacroAnalysisPanel />);

    await userEvent.click(await screen.findByTestId("macro-run-button"));

    expect(await screen.findByTestId("macro-cached-badge")).toHaveTextContent("Already analyzed");
    expect(screen.getByTestId("macro-cached-note")).toHaveTextContent("2026-08");
  });

  it("shows the supplement/month form on 422 and resubmits with the bypass params", async () => {
    runMacroCycleJudgment
      .mockRejectedValueOnce(
        new ApiError("Insufficient macro data", 422, "macro_data_insufficient", {
          readiness: { ready: false, latest_month: "2026-08", reason: "数据不足" },
        }),
      )
      .mockResolvedValueOnce({ status: "ok", cached: false, judgment: JUDGMENT });

    render(<MacroAnalysisPanel />);
    await userEvent.click(await screen.findByTestId("macro-run-button"));

    const insufficient = await screen.findByTestId("macro-insufficient");
    expect(insufficient).toHaveTextContent("2026-08");

    // Force button disabled without notes or a month.
    const forceButton = screen.getByTestId("macro-force-run-button");
    expect(forceButton).toBeDisabled();
    await userEvent.type(screen.getByTestId("macro-supplement-input"), "结合最新央行表态");
    expect(forceButton).toBeEnabled();
    await userEvent.click(forceButton);

    await waitFor(() => expect(runMacroCycleJudgment).toHaveBeenCalledTimes(2));
    expect(runMacroCycleJudgment).toHaveBeenLastCalledWith({
      economy: "中国",
      supplement: "结合最新央行表态",
    });
    expect(await screen.findByTestId("macro-judgment-detail")).toBeInTheDocument();
  });

  it("also accepts an explicit YYYY-MM month as the bypass and validates the format", async () => {
    runMacroCycleJudgment
      .mockRejectedValueOnce(
        new ApiError("Insufficient macro data", 422, "macro_data_insufficient", {
          readiness: { ready: false, latest_month: "2026-08" },
        }),
      )
      .mockResolvedValueOnce({ status: "ok", cached: false, judgment: JUDGMENT });

    render(<MacroAnalysisPanel />);
    await userEvent.click(await screen.findByTestId("macro-run-button"));
    await screen.findByTestId("macro-insufficient");

    await userEvent.type(screen.getByTestId("macro-month-input"), "2026/05");
    expect(screen.getByTestId("macro-force-run-button")).toBeDisabled();

    await userEvent.clear(screen.getByTestId("macro-month-input"));
    await userEvent.type(screen.getByTestId("macro-month-input"), "2026-05");
    await userEvent.click(screen.getByTestId("macro-force-run-button"));

    await waitFor(() =>
      expect(runMacroCycleJudgment).toHaveBeenLastCalledWith({
        economy: "中国",
        statistics_date: "2026-05",
      }),
    );
  });

  it("disables the run button while generating and renders timeout errors with retry", async () => {
    runMacroCycleJudgment
      .mockRejectedValueOnce(new ApiError("timeout", 504, "macro_llm_timeout"))
      .mockResolvedValue({ status: "ok", cached: false, judgment: JUDGMENT });

    render(<MacroAnalysisPanel />);
    await userEvent.click(await screen.findByTestId("macro-run-button"));

    const errorBox = await screen.findByTestId("macro-error");
    expect(errorBox).toHaveTextContent(/timed out/);

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("macro-judgment-detail")).toBeInTheDocument();
    expect(runMacroCycleJudgment).toHaveBeenCalledTimes(2);
  });
});
