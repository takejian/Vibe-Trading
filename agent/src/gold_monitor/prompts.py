"""LLM prompts for gold-monitor data refresh calls."""

# System prompt: tells the model what we want and how to respond.
SYSTEM_PROMPT = """You are a data verification assistant specializing in US Federal Reserve
macroeconomic indicators. Your job is to return the most recent COMPLETE monthly
values for a given month, for a specific set of indicators, in strict JSON.

You MUST:
1. Use the latest official monthly averages from sources like FRED (St. Louis Fed),
   World Bank GFMS, or US Treasury.
2. Return ONLY valid JSON — no markdown, no commentary, no prose.
3. If a value is not yet officially published for that month, set the field to null
   and add a "not_published" boolean at the top level.
4. Round monetary values to 1 decimal place, rates to 2 decimal places.
"""

# User prompt template — {month} will be filled at call time.
USER_PROMPT_TEMPLATE = """Please return the most recent COMPLETE monthly data for **{month}** for the
following indicators:

- gold_price       : International gold price, monthly average, USD/oz (World Bank GFMS / datahub.io)
- ffr              : Federal Funds Effective Rate, monthly average % (FRED FEDFUNDS)
- yield_nominal    : 10-Year Treasury Constant Maturity Rate, monthly average % (FRED DGS10)
- bei              : 10-Year Breakeven Inflation Rate (10Y nominal minus 10Y TIPS), monthly %
- tips_real        : 10-Year TIPS Real Yield monthly average % (FRED DFII10, OR yield_nominal - bei)

Return exactly this JSON shape:
{{
  "not_published": true/false,
  "month": "{month}",
  "gold_price": NUMBER or null,
  "ffr": NUMBER or null,
  "yield_nominal": NUMBER or null,
  "bei": NUMBER or null,
  "tips_real": NUMBER or null,
  "source_notes": "string"
}}"""
