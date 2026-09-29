import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HistoryList } from "../HistoryList";
import type { SwarmRunSummary } from "@/lib/api";

const RUNS: SwarmRunSummary[] = [
  {
    id: "run-1",
    preset_name: "investment_committee",
    status: "completed",
    research_target: "600519.SH",
    research_question: "long or short",
    final_report_excerpt: "bullish",
    created_at: "2026-09-24T10:00:00+00:00",
  },
  {
    id: "run-2",
    preset_name: "investment_committee",
    trial_skill: "behavioral-finance",
    kind: "skill_trial",
    status: "failed",
    research_target: "000001.SZ",
    research_question: "sentiment?",
    final_report_excerpt: "",
    created_at: "2026-09-23T10:00:00+00:00",
  },
];

describe("HistoryList", () => {
  it("submits the filter draft and resets via clear", async () => {
    const onSearch = vi.fn();
    render(
      <HistoryList
        runs={RUNS}
        loading={false}
        error=""
        onSearch={onSearch}
        onOpen={vi.fn()}
      />,
    );

    await userEvent.type(screen.getByTestId("history-filter-target"), "600519");
    await userEvent.type(screen.getByTestId("history-filter-from"), "2026-09-01");
    await userEvent.type(screen.getByTestId("history-filter-to"), "2026-09-30");
    await userEvent.click(screen.getByTestId("history-filter-search"));

    expect(onSearch).toHaveBeenCalledWith({
      target: "600519",
      from: "2026-09-01",
      to: "2026-09-30",
    });

    await userEvent.click(screen.getByTestId("history-filter-clear"));
    expect(onSearch).toHaveBeenLastCalledWith({ target: "", from: "", to: "" });
    expect((screen.getByTestId("history-filter-target") as HTMLInputElement).value).toBe("");
  });

  it("opens the run snapshot through onOpen", async () => {
    const onOpen = vi.fn();
    render(
      <HistoryList
        runs={RUNS}
        loading={false}
        error=""
        onOpen={onOpen}
        onSearch={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByTestId("open-history-run-1"));
    expect(onOpen).toHaveBeenCalledWith("run-1");
  });

  it("relabels the preset column for skill-trial mode and hides the question column", () => {
    render(
      <HistoryList
        runs={[RUNS[1]]}
        loading={false}
        error=""
        trialMode
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Skill")).toBeInTheDocument();
    expect(screen.queryByText("Question")).not.toBeInTheDocument();
    expect(screen.getByText("behavioral-finance")).toBeInTheDocument();
  });

  it("renders the empty state with the trial-mode column span", () => {
    render(
      <HistoryList runs={[]} loading={false} error="" trialMode onOpen={vi.fn()} />,
    );
    expect(screen.getByText("No evaluation records yet.")).toBeInTheDocument();
  });
});
