import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";

async function loadApiModule() {
  vi.resetModules();
  return import("../api");
}

const JUDGMENT = {
  id: 1,
  economy: "中国",
  statistics_date: "2026-08",
  current_cycle: "复苏期",
  judgment_result: "复苏期。",
  dimension_check: "增长回升。",
  meso_verify: "库存去化。",
  history_cycle_anchor: "类似 2016 年。",
  judgment_confidence: "中",
  core_support: "信贷扩张。",
  core_risk: "外需走弱。",
  extended_remark: "",
  create_time: "2026-09-24T10:00:00",
};

describe("macro api methods", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => ""),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("maps every macro endpoint with the expected URL, method and body", async () => {
    const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/macro/prompts") {
        return new Response(JSON.stringify({ status: "ok", prompts: [] }), {
          headers: { "content-type": "application/json" },
        });
      }
      if (url === "/api/macro/economies") {
        return new Response(JSON.stringify({ status: "ok", economies: ["中国"] }), {
          headers: { "content-type": "application/json" },
        });
      }
      if (url.startsWith("/api/macro/readiness")) {
        return new Response(
          JSON.stringify({ status: "ok", readiness: { ready: true, latest_month: "2026-08" } }),
          { headers: { "content-type": "application/json" } },
        );
      }
      if (url === "/api/macro/cycle/judgments" && init?.method === "POST") {
        return new Response(
          JSON.stringify({ status: "ok", cached: false, judgment: JUDGMENT }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      if (url === "/api/macro/cycle/judgments?economy=%E4%B8%AD%E5%9B%BD") {
        return new Response(
          JSON.stringify({ status: "ok", economy: "中国", judgments: [JUDGMENT] }),
          { headers: { "content-type": "application/json" } },
        );
      }
      if (url === "/api/macro/cycle/judgments/%E4%B8%AD%E5%9B%BD/2026-08") {
        return new Response(JSON.stringify({ status: "ok", judgment: JUDGMENT }), {
          headers: { "content-type": "application/json" },
        });
      }
      if (url === "/api/macro/prompts/a" && init?.method === "PUT") {
        return new Response(JSON.stringify({ status: "ok", prompt: { code: "a" } }), {
          headers: { "content-type": "application/json" },
        });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await loadApiModule();

    await api.listMacroPrompts();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/macro/prompts", expect.any(Object));

    const economies = await api.listMacroEconomies();
    expect(economies.economies).toEqual(["中国"]);

    await api.getMacroReadiness("中国");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/macro/readiness?economy=%E4%B8%AD%E5%9B%BD",
      expect.any(Object),
    );

    const ran = await api.runMacroCycleJudgment({ economy: "中国", supplement: "补充" });
    expect(ran.judgment.statistics_date).toBe("2026-08");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/macro/cycle/judgments",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ economy: "中国", supplement: "补充" }),
      }),
    );

    const history = await api.listMacroJudgments("中国");
    expect(history.judgments).toHaveLength(1);

    const detail = await api.getMacroJudgment("中国", "2026-08");
    expect(detail.judgment.current_cycle).toBe("复苏期");

    await api.updateMacroPrompt("a", "新正文");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/macro/prompts/a",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ prompt_text: "新正文" }) }),
    );
  });

  it("surfaces the structured readiness payload on a 422 envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "macro_data_insufficient",
              message: "数据不足",
              readiness: { ready: false, latest_month: "2026-08", reason: "数据不足" },
            },
          }),
          { status: 422, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    const { api, ApiError: DynamicApiError } = await loadApiModule();
    let caught: unknown;
    try {
      await api.runMacroCycleJudgment({ economy: "日本" });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(DynamicApiError);
    const apiError = caught as ApiError;
    expect(apiError.status).toBe(422);
    expect(apiError.code).toBe("macro_data_insufficient");
    expect(apiError.payload?.readiness?.latest_month).toBe("2026-08");
  });
});
