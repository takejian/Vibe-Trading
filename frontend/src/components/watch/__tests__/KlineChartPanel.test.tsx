import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KlineChartPanel } from "../KlineChartPanel";

const getWatchKlineStatus = vi.fn();
const getWatchKlineBars = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      getWatchKlineStatus: (...args: unknown[]) => getWatchKlineStatus(...args),
      getWatchKlineBars: (...args: unknown[]) => getWatchKlineBars(...args),
    },
  };
});

// Keep ECharts out of jsdom; assert the bars handed to the chart instead.
vi.mock("@/components/charts/CandlestickChart", () => ({
  CandlestickChart: ({ data }: { data: { time: string }[] }) => (
    <div data-testid="candlestick-chart">bars:{data.length}</div>
  ),
}));

const ALL = ["1d", "1w", "1mo", "1q", "1y", "30m"];

function level(interval: string, barsCount: number) {
  return {
    interval,
    required: interval !== "30m",
    status: barsCount > 0 ? "ready" : "not_fetched",
    fetch_failed: false,
    bars_count: barsCount,
    earliest_bar_time: barsCount > 0 ? "2024-09-02" : null,
    latest_bar_time: barsCount > 0 ? "2026-09-30" : null,
    last_ok_at: null,
    last_attempt_at: null,
    last_error: null,
    source: null,
  };
}

function bars(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    time: `2026-09-${String(i + 1).padStart(2, "0")}`,
    open: 10,
    high: 11,
    low: 9,
    close: 10.5,
    volume: 1000,
  }));
}

function status(barsBy: Record<string, number>) {
  return {
    items: ALL.map((interval) => level(interval, barsBy[interval] ?? 0)),
    market_ref: {
      last_trading_date: "2026-09-30",
      threshold_date: "2026-09-29",
      source: "trading_calendar",
    },
  };
}

const STATUS_TWO = status({ "30m": 30, "1d": 130 });
const STATUS_EMPTY = status({});

function barsResponse(interval: string, count: number) {
  return { symbol: "600519.SH", interval, items: bars(count) };
}

describe("KlineChartPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows tabs only for levels with stored bars and renders the first one", async () => {
    getWatchKlineStatus.mockResolvedValue(STATUS_TWO);
    getWatchKlineBars.mockImplementation(
      async (_symbol: string, interval: string) =>
        barsResponse(interval, interval === "30m" ? 30 : 130),
    );

    render(<KlineChartPanel symbol="600519.SH" />);

    await screen.findByTestId("kline-chart-body");
    expect(screen.getByTestId("candlestick-chart")).toHaveTextContent(
      "bars:30",
    );

    // 30m is the first (lowest) available tab and selected by default.
    expect(getWatchKlineBars).toHaveBeenCalledWith("600519.SH", "30m");

    // Levels without fetched data are hidden entirely.
    expect(screen.getByTestId("kline-tab-30m")).toBeInTheDocument();
    expect(screen.getByTestId("kline-tab-1d")).toBeInTheDocument();
    expect(screen.queryByTestId("kline-tab-1w")).toBeNull();
    expect(screen.queryByTestId("kline-tab-1mo")).toBeNull();
    expect(screen.queryByTestId("kline-tab-1q")).toBeNull();
    expect(screen.queryByTestId("kline-tab-1y")).toBeNull();
  });

  it("switches level tabs and caches already loaded bars", async () => {
    getWatchKlineStatus.mockResolvedValue(STATUS_TWO);
    getWatchKlineBars.mockImplementation(
      async (_symbol: string, interval: string) =>
        barsResponse(interval, interval === "30m" ? 30 : 130),
    );

    render(<KlineChartPanel symbol="600519.SH" />);
    await screen.findByTestId("kline-chart-body");

    const user = userEvent.setup();
    await user.click(screen.getByTestId("kline-tab-1d"));
    await waitFor(() =>
      expect(screen.getByTestId("candlestick-chart")).toHaveTextContent(
        "bars:130",
      ),
    );
    expect(getWatchKlineBars).toHaveBeenCalledTimes(2);

    await user.click(screen.getByTestId("kline-tab-30m"));
    expect(screen.getByTestId("candlestick-chart")).toHaveTextContent(
      "bars:30",
    );
    // No refetch for a cached level.
    expect(getWatchKlineBars).toHaveBeenCalledTimes(2);
  });

  it("shows an empty hint without tabs when no level has fetched bars", async () => {
    getWatchKlineStatus.mockResolvedValue(STATUS_EMPTY);
    render(<KlineChartPanel symbol="600519.SH" />);

    await screen.findByTestId("kline-chart-empty");
    expect(screen.queryByRole("tab")).toBeNull();
    expect(getWatchKlineBars).not.toHaveBeenCalled();
  });

  it("retries after the status request fails", async () => {
    getWatchKlineStatus.mockRejectedValueOnce(new Error("network"));
    getWatchKlineStatus.mockResolvedValue(STATUS_TWO);
    getWatchKlineBars.mockResolvedValue(barsResponse("30m", 30));

    render(<KlineChartPanel symbol="600519.SH" />);
    await screen.findByTestId("kline-chart-status-error");

    const user = userEvent.setup();
    await user.click(screen.getByText("Retry"));
    await screen.findByTestId("kline-chart-body");
  });

  it("retries bar loading after a failure", async () => {
    getWatchKlineStatus.mockResolvedValue(STATUS_TWO);
    getWatchKlineBars
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue(barsResponse("30m", 30));

    render(<KlineChartPanel symbol="600519.SH" />);
    await screen.findByTestId("kline-bars-error");

    const user = userEvent.setup();
    await user.click(screen.getByText("Retry"));
    await screen.findByTestId("kline-chart-body");
  });
});
