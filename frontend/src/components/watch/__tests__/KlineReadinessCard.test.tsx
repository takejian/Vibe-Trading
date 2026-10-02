import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KlineReadinessCard } from "../KlineReadinessCard";

const getWatchKlineStatus = vi.fn();
const getWatchKlineSources = vi.fn();
const updateWatchKline = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      getWatchKlineStatus: (...args: unknown[]) => getWatchKlineStatus(...args),
      getWatchKlineSources: (...args: unknown[]) => getWatchKlineSources(...args),
      updateWatchKline: (...args: unknown[]) => updateWatchKline(...args),
    },
  };
});

const ALL_INTERVALS = ["1d", "1w", "1mo", "1q", "1y", "30m"];

const SOURCES = {
  items: [
    {
      id: "tencent",
      available: true,
      requires_auth: false,
      reason: null,
      intervals: ALL_INTERVALS,
    },
    {
      id: "mootdx",
      available: false,
      requires_auth: false,
      reason: "not_installed",
      intervals: [],
    },
    {
      id: "eastmoney",
      available: true,
      requires_auth: false,
      reason: null,
      intervals: ALL_INTERVALS,
    },
    {
      id: "tushare",
      available: false,
      requires_auth: true,
      reason: "needs_auth",
      intervals: [],
    },
  ],
};

function level(
  interval: string,
  status: string,
  over: Record<string, unknown> = {},
) {
  return {
    interval,
    required: interval !== "30m",
    status,
    fetch_failed: status === "failed",
    bars_count: status === "ready" ? 100 : 0,
    earliest_bar_time: null,
    latest_bar_time: status === "ready" ? "2026-09-30" : null,
    last_ok_at: status === "ready" ? "2026-09-30T15:00:00" : null,
    last_attempt_at: "2026-09-30T15:00:00",
    last_error: status === "failed" ? "upstream timeout" : null,
    source: null,
    ...over,
  };
}

const INITIAL = {
  items: [
    level("1d", "ready", { bars_count: 120, source: "eastmoney" }),
    level("1w", "failed"),
    level("1mo", "not_fetched"),
    level("1q", "insufficient", { bars_count: 8 }),
    level("1y", "ready", { bars_count: 6 }),
    level("30m", "not_fetched", { required: false, fetch_failed: false }),
  ],
  market_ref: {
    last_trading_date: "2026-09-30",
    threshold_date: "2026-09-29",
    source: "trading_calendar",
  },
};

function readyResponse(intervals: string[]) {
  return {
    items: [
      ...INITIAL.items.map((item) =>
        intervals.includes(item.interval)
          ? level(item.interval, "ready", { source: "tencent" })
          : item,
      ),
    ],
    market_ref: INITIAL.market_ref,
  };
}

describe("KlineReadinessCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    getWatchKlineStatus.mockResolvedValue(INITIAL);
    getWatchKlineSources.mockResolvedValue(SOURCES);
    updateWatchKline.mockImplementation(
      async (_symbol: string, intervals: string[], _source?: string) =>
        readyResponse(intervals),
    );
  });

  it("renders the five required levels with status badges and the failure hint", async () => {
    render(<KlineReadinessCard symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("kline-status-1d")).toHaveTextContent("Ready"),
    );
    expect(screen.getByTestId("kline-status-1w")).toHaveTextContent("Fetch failed");
    expect(screen.getByTestId("kline-status-1mo")).toHaveTextContent("Not fetched");
    expect(screen.getByTestId("kline-status-1q")).toHaveTextContent("Insufficient");
    expect(screen.getByTestId("kline-status-1y")).toHaveTextContent("Ready");

    // The vendor that produced the current bars is shown next to the status.
    expect(screen.getByTestId("kline-source-badge-1d")).toHaveTextContent(
      "Eastmoney",
    );

    // Failed/not-ready required levels each expose an inline retry button;
    // the ready levels do not.
    expect(screen.queryByTestId("kline-retry-1d")).toBeNull();
    expect(screen.getByTestId("kline-retry-1w")).toBeInTheDocument();
    expect(screen.getByTestId("kline-retry-1mo")).toBeInTheDocument();
    expect(screen.getByTestId("kline-retry-1q")).toBeInTheDocument();
    expect(screen.queryByTestId("kline-retry-1y")).toBeNull();

    // The operational retry guidance is present while a required level failed.
    expect(screen.getByTestId("kline-fail-hint")).toBeInTheDocument();

    // The optional 30m level lives in its own dashed panel with its own button.
    expect(screen.getByTestId("kline-30m")).toBeInTheDocument();
    expect(screen.getByTestId("kline-30m-btn")).toHaveTextContent(
      "Try fetching 30-minute K-lines",
    );
  });

  it("lists vendors in settings order and defaults to the first available one", async () => {
    render(<KlineReadinessCard symbol="600519.SH" />);
    const select = await screen.findByTestId("kline-source-select");
    await waitFor(() => expect(select).toHaveValue("tencent"));
    const options = Array.from(select.querySelectorAll("option"));
    expect(options.map((option) => option.value)).toEqual([
      "tencent",
      "mootdx",
      "eastmoney",
      "tushare",
    ]);
    // Unavailable vendors are disabled and carry the machine reason.
    expect(
      options.find((option) => option.value === "mootdx")?.disabled,
    ).toBe(true);
    expect(
      options.find((option) => option.value === "mootdx"),
    ).toHaveTextContent("not installed");
    expect(
      options.find((option) => option.value === "tushare")?.disabled,
    ).toBe(true);
    expect(
      options.find((option) => option.value === "tencent")?.disabled,
    ).toBe(false);
  });

  it("updates all five required levels at once with the selected vendor (never the optional 30m)", async () => {
    const user = userEvent.setup();
    render(<KlineReadinessCard symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("kline-update-all")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("kline-update-all"));
    await waitFor(() => expect(updateWatchKline).toHaveBeenCalledTimes(1));
    expect(updateWatchKline).toHaveBeenCalledWith(
      "600519.SH",
      ["1d", "1w", "1mo", "1q", "1y"],
      "tencent",
    );
    await waitFor(() =>
      expect(screen.getByTestId("kline-message")).toHaveTextContent(
        "K-line update finished",
      ),
    );
    // After the successful bulk refresh every required row is ready and the
    // failure hint disappears.
    expect(screen.queryByTestId("kline-fail-hint")).toBeNull();
    expect(screen.getByTestId("kline-status-1mo")).toHaveTextContent("Ready");
  });

  it("retries a single level on demand with the selected vendor", async () => {
    const user = userEvent.setup();
    render(<KlineReadinessCard symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("kline-retry-1q")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("kline-retry-1q"));
    await waitFor(() => expect(updateWatchKline).toHaveBeenCalledTimes(1));
    expect(updateWatchKline).toHaveBeenCalledWith("600519.SH", ["1q"], "tencent");
    expect(screen.getByTestId("kline-status-1q")).toHaveTextContent("Ready");
  });

  it("fetches the optional 30m level independently and annotates only its own status", async () => {
    const user = userEvent.setup();
    render(<KlineReadinessCard symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("kline-30m-btn")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("kline-30m-btn"));
    await waitFor(() => expect(updateWatchKline).toHaveBeenCalledTimes(1));
    expect(updateWatchKline).toHaveBeenCalledWith(
      "600519.SH",
      ["30m"],
      "tencent",
    );
    // Weekly is still failed -> the required-level failure hint stays.
    expect(screen.getByTestId("kline-fail-hint")).toBeInTheDocument();
    expect(screen.getByTestId("kline-status-30m")).toHaveTextContent("Ready");
  });

  it("remembers the chosen vendor in localStorage and sends it on update", async () => {
    const user = userEvent.setup();
    render(<KlineReadinessCard symbol="600519.SH" />);
    const select = await screen.findByTestId("kline-source-select");
    await waitFor(() => expect(select).toHaveValue("tencent"));
    await user.selectOptions(select, "eastmoney");
    expect(localStorage.getItem("vibe_watch_kline_source")).toBe("eastmoney");
    await user.click(screen.getByTestId("kline-update-all"));
    await waitFor(() => expect(updateWatchKline).toHaveBeenCalledTimes(1));
    expect(updateWatchKline).toHaveBeenCalledWith(
      "600519.SH",
      ["1d", "1w", "1mo", "1q", "1y"],
      "eastmoney",
    );
  });

  it("restores the remembered vendor when it is still available", async () => {
    localStorage.setItem("vibe_watch_kline_source", "eastmoney");
    render(<KlineReadinessCard symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("kline-source-select")).toHaveValue("eastmoney"),
    );
  });

  it("pops up an error dialog listing failed levels, the attempted vendor and the error text", async () => {
    const user = userEvent.setup();
    updateWatchKline.mockResolvedValue({
      items: [
        level("1d", "ready"),
        level("1w", "ready"),
        level("1mo", "failed", {
          // Old bars were Tencent's; the failed attempt below used Eastmoney.
          source: "tencent",
          last_error: "RemoteDisconnected: eastmoney CDN reset",
        }),
        level("1q", "ready"),
        level("1y", "ready"),
        level("30m", "not_fetched", { required: false, fetch_failed: false }),
      ],
      market_ref: INITIAL.market_ref,
    });
    render(<KlineReadinessCard symbol="600519.SH" />);
    const select = await screen.findByTestId("kline-source-select");
    await waitFor(() => expect(select).toHaveValue("tencent"));
    await user.selectOptions(select, "eastmoney");
    await user.click(screen.getByTestId("kline-update-all"));

    const dialog = await screen.findByTestId("kline-error-dialog");
    expect(dialog).toBeInTheDocument();
    const row = screen.getByTestId("kline-error-row-1mo");
    expect(row).toHaveTextContent("Monthly");
    // The error is attributed to the attempted vendor (Eastmoney), not the
    // old bars' provenance shown in the table (Tencent).
    expect(row).toHaveTextContent("Eastmoney");
    expect(row).not.toHaveTextContent("Tencent");
    expect(row).toHaveTextContent("RemoteDisconnected: eastmoney CDN reset");
    expect(updateWatchKline).toHaveBeenCalledWith(
      "600519.SH",
      ["1d", "1w", "1mo", "1q", "1y"],
      "eastmoney",
    );

    // Closing the dialog dismisses it.
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByTestId("kline-error-dialog")).toBeNull(),
    );
  });

  it("retries only the failed levels from inside the error dialog", async () => {
    const user = userEvent.setup();
    updateWatchKline
      .mockResolvedValueOnce({
        items: [
          level("1d", "ready"),
          level("1w", "failed", {
            source: "tencent",
            last_error: "boom week",
          }),
          level("1mo", "failed", {
            source: "tencent",
            last_error: "boom month",
          }),
          level("1q", "ready"),
          level("1y", "ready"),
          level("30m", "not_fetched", { required: false, fetch_failed: false }),
        ],
        market_ref: INITIAL.market_ref,
      })
      .mockImplementation(
        async (_symbol: string, intervals: string[], _source?: string) =>
          readyResponse(intervals),
      );
    render(<KlineReadinessCard symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("kline-update-all")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("kline-update-all"));
    await screen.findByTestId("kline-error-dialog");
    await user.click(
      screen.getByRole("button", { name: "Retry failed levels" }),
    );
    await waitFor(() => expect(updateWatchKline).toHaveBeenCalledTimes(2));
    expect(updateWatchKline).toHaveBeenLastCalledWith(
      "600519.SH",
      ["1w", "1mo"],
      "tencent",
    );
    await waitFor(() =>
      expect(screen.queryByTestId("kline-error-dialog")).toBeNull(),
    );
  });

  it("pops up the error dialog when the optional 30m fetch fails", async () => {
    const user = userEvent.setup();
    updateWatchKline.mockResolvedValue({
      items: [
        ...INITIAL.items.filter((item) => item.interval !== "30m"),
        level("30m", "failed", {
          required: false,
          source: "tencent",
          last_error: "no minute bars",
        }),
      ],
      market_ref: INITIAL.market_ref,
    });
    render(<KlineReadinessCard symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("kline-30m-btn")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("kline-30m-btn"));
    const dialog = await screen.findByTestId("kline-error-dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTestId("kline-error-row-30m")).toHaveTextContent(
      "no minute bars",
    );
  });

  it("pops up the error dialog carrying the request error when the update request itself fails", async () => {
    const user = userEvent.setup();
    updateWatchKline.mockRejectedValueOnce(
      new Error("unknown data source: mirage"),
    );
    render(<KlineReadinessCard symbol="600519.SH" />);
    await waitFor(() =>
      expect(screen.getByTestId("kline-update-all")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("kline-update-all"));
    const row = await screen.findByTestId("kline-error-row-request");
    expect(row).toHaveTextContent("unknown data source: mirage");
    // Request-level failure has no per-level retry target.
    expect(
      screen.getByRole("button", { name: "Retry failed levels" }),
    ).toBeDisabled();
  });

  it("shows a load error with retry when the status endpoint fails", async () => {
    const user = userEvent.setup();
    getWatchKlineStatus.mockRejectedValueOnce(new Error("network"));
    render(<KlineReadinessCard symbol="600519.SH" />);
    const alert = await screen.findByTestId("kline-load-error");
    expect(alert).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(getWatchKlineStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("kline-status-1d")).toBeInTheDocument();
  });
});
