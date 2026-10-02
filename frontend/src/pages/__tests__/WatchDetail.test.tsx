import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router";
import { ApiError } from "@/lib/api";
import { WatchDetail } from "../WatchDetail";

const getWatchProfile = vi.fn();
const refreshWatchQuotes = vi.fn();
const refreshWatchProfile = vi.fn();
const getObjective = vi.fn();
const startObjectiveFetch = vi.fn();
const listWatchAgents = vi.fn();
const listWatchAnalyses = vi.fn();
const listChanlun = vi.fn();
const getWatchKlineStatus = vi.fn();
const getWatchKlineSources = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      getWatchProfile: (...a: unknown[]) => getWatchProfile(...a),
      refreshWatchQuotes: (...a: unknown[]) => refreshWatchQuotes(...a),
      refreshWatchProfile: (...a: unknown[]) => refreshWatchProfile(...a),
      getObjective: (...a: unknown[]) => getObjective(...a),
      startObjectiveFetch: (...a: unknown[]) => startObjectiveFetch(...a),
      listWatchAgents: (...a: unknown[]) => listWatchAgents(...a),
      listWatchAnalyses: (...a: unknown[]) => listWatchAnalyses(...a),
      listChanlun: (...a: unknown[]) => listChanlun(...a),
      getWatchKlineStatus: (...a: unknown[]) => getWatchKlineStatus(...a),
      getWatchKlineSources: (...a: unknown[]) => getWatchKlineSources(...a),
    },
  };
});

vi.mock("@/components/swarm/RunView", () => ({
  RunView: ({ runId }: { runId: string }) => (
    <div data-testid="mock-run-view">RUN {runId}</div>
  ),
}));

const PROFILE = {
  symbol: "600519.SH",
  instrument: { symbol: "600519.SH", list_date: "2001-08-27", industry: "白酒" },
  latest_valuation: { pe_ttm: 25.6 },
  entry: {
    symbol: "600519.SH",
    name: "贵州茅台",
    industry: "白酒",
    added_at: "2026-09-01T00:00:00+00:00",
    updated_at: "2026-10-01T00:00:00+00:00",
    quote: {
      price: 1500,
      total_market_cap: 1.88e12,
      pe: 25.6,
      pb: 8.1,
      industry: "白酒",
      quote_updated_at: "2026-10-01T08:00:00+00:00",
    },
  },
};

const EMPTY_OBJECTIVE = {
  symbol: "600519.SH",
  raw: { instrument: [], daily_bar: [], valuation: [], financial: [] },
  fetches: [],
};

function renderDetail() {
  const router = createMemoryRouter(
    [
      { path: "/watch/:symbol", element: <WatchDetail /> },
      { path: "/watch", element: <div data-testid="list-landed">LIST</div> },
    ],
    { initialEntries: ["/watch/600519.SH"] },
  );
  return render(<RouterProvider router={router} />);
}

describe("WatchDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getWatchProfile.mockResolvedValue(PROFILE);
    refreshWatchQuotes.mockResolvedValue({ symbol: "600519.SH", quote: PROFILE.entry.quote, updated_at: "x" });
    refreshWatchProfile.mockResolvedValue({
      symbol: "600519.SH",
      name: "贵州茅台股份",
      industry: "白酒",
      list_date: "2001-08-27",
      registered_capital: 1256000000,
      total_shares: 1.256e9,
      updated_at: "2026-10-01T09:00:00+00:00",
    });
    getObjective.mockResolvedValue(EMPTY_OBJECTIVE);
    startObjectiveFetch.mockResolvedValue({
      id: "run-fetch-1",
      status: "pending",
      kind: "role_run",
      trial_role: "equity_research_team:stock_picker",
    });
    listWatchAgents.mockResolvedValue({ items: [] });
    listWatchAnalyses.mockResolvedValue({ items: [] });
    listChanlun.mockResolvedValue({ items: [] });
    getWatchKlineSources.mockResolvedValue({
      items: [
        { id: "tencent", available: true, requires_auth: false, reason: null,
          intervals: ["1d", "1w", "1mo", "1q", "1y", "30m"] },
        { id: "eastmoney", available: true, requires_auth: false, reason: null,
          intervals: ["1d", "1w", "1mo", "1q", "1y", "30m"] },
      ],
    });
    getWatchKlineStatus.mockResolvedValue({
      items: [
        { interval: "1d", required: true, status: "ready", fetch_failed: false, bars_count: 120, latest_bar_time: "2026-09-30", last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00", last_error: null, earliest_bar_time: null },
        { interval: "1w", required: true, status: "ready", fetch_failed: false, bars_count: 60, latest_bar_time: "2026-09-30", last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00", last_error: null, earliest_bar_time: null },
        { interval: "1mo", required: true, status: "ready", fetch_failed: false, bars_count: 24, latest_bar_time: "2026-09-30", last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00", last_error: null, earliest_bar_time: null },
        { interval: "1q", required: true, status: "ready", fetch_failed: false, bars_count: 12, latest_bar_time: "2026-09-30", last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00", last_error: null, earliest_bar_time: null },
        { interval: "1y", required: true, status: "ready", fetch_failed: false, bars_count: 5, latest_bar_time: "2026-09-30", last_ok_at: "2026-09-30T15:00:00", last_attempt_at: "2026-09-30T15:00:00", last_error: null, earliest_bar_time: null },
        { interval: "30m", required: false, status: "not_fetched", fetch_failed: false, bars_count: 0, latest_bar_time: null, last_ok_at: null, last_attempt_at: null, last_error: null, earliest_bar_time: null },
      ],
      market_ref: { last_trading_date: "2026-09-30", threshold_date: "2026-09-29", source: "trading_calendar" },
    });
  });

  it("renders overview fields with No-data placeholders for missing values", async () => {
    renderDetail();
    await waitFor(() => expect(screen.getByRole("heading", { name: /贵州茅台/ })).toBeInTheDocument());
    expect(screen.getByText("2001-08-27")).toBeInTheDocument();
    expect(screen.getByText("2026-10-01T08:00:00+00:00")).toBeInTheDocument();
    // Registered capital unknown until profile refresh.
    expect(screen.getAllByText("No data").length).toBeGreaterThan(0);
  });

  it("refresh-quotes button calls the quote endpoint and shows success", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });
    await user.click(screen.getByTestId("refresh-quotes-btn"));
    await waitFor(() =>
      expect(refreshWatchQuotes).toHaveBeenCalledWith("600519.SH"),
    );
    expect(screen.getByTestId("refresh-msg").textContent).toContain("Updated");
    // Profile is reloaded after refresh.
    await waitFor(() => expect(getWatchProfile).toHaveBeenCalledTimes(2));
  });

  it("surfaces refresh failure with a retryable error message", async () => {
    const user = userEvent.setup();
    refreshWatchQuotes.mockRejectedValue(new ApiError("bad", 502));
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });
    await user.click(screen.getByTestId("refresh-quotes-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("refresh-msg").textContent).toContain(
        "Update failed",
      ),
    );
    // Still retryable: button remains enabled.
    expect(screen.getByTestId("refresh-quotes-btn")).toBeEnabled();
  });

  it("refresh-profile fills the company profile fields", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });
    await user.click(screen.getByTestId("refresh-profile-btn"));
    await waitFor(() =>
      expect(refreshWatchProfile).toHaveBeenCalledWith("600519.SH"),
    );
    await waitFor(() => expect(screen.getByText("1,256,000,000")).toBeInTheDocument());
  });

  it("renders four empty objective sections and drives objective fetch", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });
    await user.click(screen.getByRole("tab", { name: "Objective data" }));

    await waitFor(() => expect(getObjective).toHaveBeenCalledTimes(1));
    // M16: the Chanlun multi-level K-line readiness card sits on top of the
    // objective tab and lists all five required levels.
    await waitFor(() => expect(getWatchKlineStatus).toHaveBeenCalledWith("600519.SH"));
    expect(screen.getByTestId("kline-card")).toBeInTheDocument();
    expect(screen.getByTestId("kline-update-all")).toBeInTheDocument();
    expect(screen.getByTestId("kline-30m-btn")).toBeInTheDocument();
    // Four empty sections.
    expect(screen.getAllByText("No data").length).toBe(4);
    expect(screen.getByTestId("objective-records-empty")).toBeInTheDocument();

    // Empty note -> button disabled with hint.
    expect(screen.getByTestId("objective-fetch-btn")).toBeDisabled();
    await user.type(screen.getByTestId("objective-note"), "近三年分红");
    expect(screen.getByTestId("objective-fetch-btn")).toBeEnabled();
    await user.click(screen.getByTestId("objective-fetch-btn"));
    await waitFor(() =>
      expect(startObjectiveFetch).toHaveBeenCalledWith("600519.SH", "近三年分红"),
    );
    expect(screen.getByTestId("objective-run-id").textContent).toContain("run-fetch-1");
    // Records refreshed after launch.
    expect(getObjective).toHaveBeenCalledTimes(2);
  });

  it("clears the fetch-running hint once the run is archived (I5)", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });
    await user.click(screen.getByRole("tab", { name: "Objective data" }));
    await waitFor(() => expect(getObjective).toHaveBeenCalledTimes(1));

    await user.type(screen.getByTestId("objective-note"), "近三年分红");
    await user.click(screen.getByTestId("objective-fetch-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("objective-run-id")).toHaveTextContent("run-fetch-1"),
    );

    // Re-entering the tab after the run archived -> hint disappears.
    getObjective.mockResolvedValueOnce({
      symbol: "600519.SH",
      raw: EMPTY_OBJECTIVE.raw,
      fetches: [
        {
          id: "rec-x",
          symbol: "600519.SH",
          category: "agent_fetch",
          request_note: "近三年分红",
          payload: "归档正文",
          source: "run",
          run_id: "run-fetch-1",
          created_by: "system",
          created_at: "2026-09-12T10:00:00+00:00",
        },
      ],
    });
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    await user.click(screen.getByRole("tab", { name: "Objective data" }));
    await waitFor(() =>
      expect(screen.getByTestId("objective-record-payload")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("objective-run-id")).toBeNull();
  });

  it("shows a fetch failure message (409)", async () => {
    const user = userEvent.setup();
    startObjectiveFetch.mockRejectedValue(new ApiError("busy", 409));
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });
    await user.click(screen.getByRole("tab", { name: "Objective data" }));
    await waitFor(() => expect(getObjective).toHaveBeenCalledTimes(1));
    await user.type(screen.getByTestId("objective-note"), "补充数据");
    await user.click(screen.getByTestId("objective-fetch-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("objective-fetch-error")).toBeInTheDocument(),
    );
  });

  it("renders archived fetch records with note/source/time/payload", async () => {
    getObjective.mockResolvedValue({
      symbol: "600519.SH",
      raw: EMPTY_OBJECTIVE.raw,
      fetches: [
        {
          id: "rec-1",
          symbol: "600519.SH",
          category: "agent_fetch",
          request_note: "近三年分红",
          payload: "分红报告正文",
          source: "run",
          run_id: "run-x",
          created_by: "system",
          created_at: "2026-09-12T10:00:00+00:00",
        },
      ],
    });
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });
    await user.click(screen.getByRole("tab", { name: "Objective data" }));
    await waitFor(() =>
      expect(screen.getByTestId("objective-record-payload")).toHaveTextContent(
        "分红报告正文",
      ),
    );
    expect(screen.getByText(/近三年分红/)).toBeInTheDocument();
  });

  it("shows a 404 guide with a way back to the list", async () => {
    getWatchProfile.mockRejectedValue(new ApiError("missing", 404));
    renderDetail();
    await waitFor(() =>
      expect(screen.getByTestId("watch-detail-404")).toBeInTheDocument(),
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: /Back to watchlist/ }));
    await waitFor(() => expect(screen.getByTestId("list-landed")).toBeInTheDocument());
  });

  it("loads fundamental, technical (+chanlun) and general catalogs per tab", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });

    await user.click(screen.getByRole("tab", { name: "Fundamentals" }));
    await waitFor(() =>
      expect(listWatchAgents).toHaveBeenCalledWith("fundamental"),
    );

    await user.click(screen.getByRole("tab", { name: "Technical" }));
    await waitFor(() =>
      expect(listWatchAgents).toHaveBeenCalledWith("technical"),
    );
    await waitFor(() => expect(listChanlun).toHaveBeenCalledWith("600519.SH", {
      from: undefined,
      to: undefined,
      limit: 50,
    }));
    expect(screen.getByTestId("chanlun-history")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "AI analysis" }));
    await waitFor(() => expect(listWatchAgents).toHaveBeenCalledWith("general"));
  });

  it("shows a retryable load error for non-404 profile failures (I3)", async () => {
    getWatchProfile.mockRejectedValueOnce(new ApiError("boom", 502));
    const user = userEvent.setup();
    renderDetail();
    await waitFor(() =>
      expect(screen.getByTestId("watch-detail-load-error")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("watch-detail-404")).toBeNull();
    // Retry recovers.
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("heading", { name: /贵州茅台/ });
  });

  it("fundamental tab shows only the financial section, no fetch box (N7)", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });

    await user.click(screen.getByRole("tab", { name: "Fundamentals" }));
    await waitFor(() => expect(getObjective).toHaveBeenCalledTimes(1));
    // Only the financial RawTable -> a single No-data placeholder.
    expect(screen.getAllByText("No data").length).toBe(1);
    expect(screen.queryByTestId("objective-note")).toBeNull();
    expect(screen.queryByTestId("objective-fetch-btn")).toBeNull();
    expect(screen.queryByTestId("objective-records-empty")).toBeNull();

    // Objective tab keeps the full four-section panel plus fetch controls.
    await user.click(screen.getByRole("tab", { name: "Objective data" }));
    await waitFor(() => expect(getObjective).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText("No data").length).toBe(4);
    expect(screen.getByTestId("objective-note")).toBeInTheDocument();
    expect(screen.getByTestId("objective-records-empty")).toBeInTheDocument();
  });

  it("re-fetches objective data every time the objective tab is entered (I5)", async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole("heading", { name: /贵州茅台/ });

    await user.click(screen.getByRole("tab", { name: "Objective data" }));
    await waitFor(() => expect(getObjective).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    await user.click(screen.getByRole("tab", { name: "Objective data" }));
    await waitFor(() => expect(getObjective).toHaveBeenCalledTimes(2));
  });
});
