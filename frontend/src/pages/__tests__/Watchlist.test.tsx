import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router";
import { ApiError } from "@/lib/api";
import { Watchlist } from "../Watchlist";

const listWatch = vi.fn();
const addWatch = vi.fn();
const removeWatch = vi.fn();
const searchWatch = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listWatch: (...args: unknown[]) => listWatch(...args),
      addWatch: (...args: unknown[]) => addWatch(...args),
      removeWatch: (...args: unknown[]) => removeWatch(...args),
      searchWatch: (...args: unknown[]) => searchWatch(...args),
    },
  };
});

function quote(over: Record<string, number | string | null> = {}) {
  return {
    price: 1500,
    total_market_cap: 1.88e12,
    pe: 25.6,
    pb: 8.1,
    industry: "白酒",
    quote_updated_at: "2026-10-01T00:00:00+00:00",
    ...over,
  };
}

const ENTRIES = [
  {
    symbol: "600519.SH",
    name: "贵州茅台",
    industry: "白酒",
    added_at: "2026-09-01T00:00:00+00:00",
    updated_at: "2026-10-01T00:00:00+00:00",
    quote: quote(),
  },
  {
    symbol: "000001.SZ",
    name: "平安银行",
    industry: null,
    added_at: "2026-09-02T00:00:00+00:00",
    updated_at: "2026-10-01T00:00:00+00:00",
    quote: quote({
      price: 11.2,
      total_market_cap: null,
      pe: 4.3,
      pb: 0.5,
      industry: null,
    }),
  },
];

function renderPage() {
  const router = createMemoryRouter(
    [
      { path: "/watch", element: <Watchlist /> },
      {
        path: "/watch/:symbol",
        element: <div data-testid="detail-landed">DETAIL</div>,
      },
    ],
    { initialEntries: ["/watch"] },
  );
  return render(<RouterProvider router={router} />);
}

describe("Watchlist page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listWatch.mockResolvedValue({ items: ENTRIES, quote_error: null });
    addWatch.mockResolvedValue(ENTRIES[0]);
    removeWatch.mockResolvedValue({ ok: true });
    searchWatch.mockResolvedValue({ items: [] });
  });

  it("renders all quote fields and a No-data placeholder for nulls", async () => {
    renderPage();
    expect(screen.getByTestId("watch-loading")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());
    expect(screen.getByText("600519.SH")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getAllByText("No data").length).toBeGreaterThan(0);
  });

  it("sorts numeric columns both directions with nulls always last", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());

    const rows = () =>
      screen
        .getAllByRole("row")
        .slice(1)
        .map((r) => r.textContent ?? "");

    // Market cap desc/asc: null cap (Ping An) always last.
    fireEvent.click(screen.getByRole("button", { name: /Market cap/ }));
    expect(rows()[0]).toContain("贵州茅台");
    expect(rows()[1]).toContain("平安银行");
    fireEvent.click(screen.getByRole("button", { name: /Market cap/ }));
    expect(rows()[0]).toContain("贵州茅台");
    expect(rows()[1]).toContain("平安银行");
    // Price desc -> Moutai first; asc -> Ping An first.
    fireEvent.click(screen.getByRole("button", { name: /Price/ }));
    expect(rows()[0]).toContain("贵州茅台");
    fireEvent.click(screen.getByRole("button", { name: /Price/ }));
    expect(rows()[0]).toContain("平安银行");
    // Third click clears sort -> insertion order restored.
    fireEvent.click(screen.getByRole("button", { name: /Price/ }));
    expect(rows()[0]).toContain("贵州茅台");
  });

  it("checkboxes change only visuals; no batch action appears", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());

    const box = screen.getByLabelText("Select 贵州茅台");
    const buttonCount = screen.getAllByRole("button").length;
    await user.click(box);
    expect(box).toBeChecked();
    // Selection is purely visual: no new (bulk-action) controls appear and
    // no API mutation fires.
    expect(screen.getAllByRole("button").length).toBe(buttonCount);
    expect(screen.queryByRole("button", { name: /bulk|selected/i })).toBeNull();
    expect(listWatch).toHaveBeenCalledTimes(1);
    expect(removeWatch).not.toHaveBeenCalled();
    expect(addWatch).not.toHaveBeenCalled();
  });

  it("debounces search, adds a candidate, and refreshes the list", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());

    searchWatch.mockResolvedValue({
      items: [{ symbol: "300750.SZ", name: "宁德时代", industry: "电池" }],
    });

    await user.click(screen.getByRole("button", { name: "Add symbol" }));
    const input = screen.getByTestId("watch-search-input");
    await user.type(input, "宁");
    // Debounce: no search yet (>=300ms).
    expect(searchWatch).not.toHaveBeenCalled();
    const candidate = await screen.findByText("宁德时代", undefined, {
      timeout: 1500,
    });
    expect(candidate).toBeInTheDocument();
    expect(searchWatch).toHaveBeenCalledWith("宁");

    await user.click(screen.getAllByRole("button", { name: "Add symbol" })[1]);
    await waitFor(() => expect(addWatch).toHaveBeenCalledTimes(1));
    expect(addWatch).toHaveBeenCalledWith({
      symbol: "300750.SZ",
      name: "宁德时代",
      industry: "电池",
    });
    // List refreshed after add.
    await waitFor(() => expect(listWatch).toHaveBeenCalledTimes(2));
  });

  it("shows the backend 409 message and keeps the dialog open", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());
    searchWatch.mockResolvedValue({
      items: [{ symbol: "300750.SZ", name: "宁德时代", industry: "电池" }],
    });
    addWatch.mockRejectedValue(new ApiError("Already watched", 409));

    await user.click(screen.getByRole("button", { name: "Add symbol" }));
    await user.type(screen.getByTestId("watch-search-input"), "宁德");
    await screen.findByText("宁德时代", undefined, { timeout: 1500 });
    await user.click(screen.getAllByRole("button", { name: "Add symbol" })[1]);

    await waitFor(() =>
      expect(screen.getByTestId("watch-add-error").textContent).toContain(
        "300750.SZ",
      ),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renders the no-result state", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Add symbol" }));
    await user.type(screen.getByTestId("watch-search-input"), "不存在");
    expect(
      await screen.findByText("No matching A-share symbols", undefined, {
        timeout: 1500,
      }),
    ).toBeInTheDocument();
  });

  it("requires confirm for unwatch; cancel does nothing, confirm removes", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());

    const unwatch = screen.getAllByRole("button", { name: "Unwatch" })[0];
    await user.click(unwatch);
    const dialog = screen.getByRole("alertdialog");
    expect(
      within(dialog).getByText("Remove from watchlist?"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(removeWatch).not.toHaveBeenCalled();

    await user.click(unwatch);
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(removeWatch).toHaveBeenCalledWith("600519.SH"),
    );
  });

  it("keeps the confirm dialog open and shows an error when unwatch fails (N8)", async () => {
    removeWatch.mockRejectedValueOnce(new ApiError("boom", 502));
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());

    await user.click(screen.getAllByRole("button", { name: "Unwatch" })[0]);
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(screen.getByTestId("remove-error")).toBeInTheDocument(),
    );
    // Dialog stays open so the user can retry.
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(removeWatch).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).toBeNull(),
    );
  });

  it("navigates to the detail page via View", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "View" })[0]);
    await waitFor(() =>
      expect(screen.getByTestId("detail-landed")).toBeInTheDocument(),
    );
  });

  it("AI batch compare only shows a hint and fires no API call", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockClear();
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("贵州茅台")).toBeInTheDocument());
    fetchSpy.mockClear();

    await user.click(screen.getByTestId("ai-compare-btn"));
    expect(screen.getByTestId("compare-hint")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(listWatch).toHaveBeenCalledTimes(1);
    fetchSpy.mockRestore();
  });

  it("renders the empty state", async () => {
    listWatch.mockResolvedValue({ items: [], quote_error: null });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("watch-empty")).toBeInTheDocument(),
    );
    expect(screen.getByText("No symbols yet")).toBeInTheDocument();
  });
});
