/**
 * Product-defined macro catalog for the "智能体团队 / 宏观角色" tabs.
 *
 * The taxonomy (4 teams under 4 themes; 18 roles under 7 themes) is fixed by
 * the macro BDD (docs/BDD_宏观经济.md). All dynamic content — team title,
 * role name/purpose, full profile — is resolved from the existing swarm APIs
 * via the refs declared here; this module holds no prompts or data.
 */

export interface MacroTeamTheme {
  /** i18n key (macro.teamTheme.*). */
  themeKey: string;
  presetName: string;
}

/** Team tab order: 宏观策略 / 宏观利率外汇 / 地缘分析 / 资产轮转. */
export const MACRO_TEAM_THEMES: MacroTeamTheme[] = [
  { themeKey: "macro.teamTheme.strategy", presetName: "macro_strategy_forum" },
  { themeKey: "macro.teamTheme.ratesFx", presetName: "macro_rates_fx_desk" },
  { themeKey: "macro.teamTheme.geopolitical", presetName: "geopolitical_war_room" },
  { themeKey: "macro.teamTheme.rotation", presetName: "sector_rotation_team" },
];

export interface MacroRoleTheme {
  /** i18n key (macro.roleTheme.*). */
  themeKey: string;
  /** Built-in role refs of the form "preset_name:agent_id". */
  refs: string[];
}

/**
 * Role tab taxonomy (18 refs total). Refs were checked against the preset
 * YAMLs in agent/src/swarm/presets/.
 */
export const MACRO_ROLE_THEMES: MacroRoleTheme[] = [
  {
    themeKey: "macro.roleTheme.cycle",
    refs: [
      "macro_strategy_forum:global_economist",
      "macro_strategy_forum:domestic_economist",
      "sector_rotation_team:cycle_analyst",
      "equity_research_team:macro_analyst",
    ],
  },
  {
    themeKey: "macro.roleTheme.ratesFx",
    refs: [
      "macro_rates_fx_desk:rates_analyst",
      "macro_rates_fx_desk:fx_strategist",
    ],
  },
  {
    themeKey: "macro.roleTheme.commodityInflation",
    refs: [
      "macro_rates_fx_desk:commodity_inflation_analyst",
      "geopolitical_war_room:energy_analyst",
    ],
  },
  {
    themeKey: "macro.roleTheme.geopoliticalSupplyChain",
    refs: [
      "geopolitical_war_room:geopolitical_analyst",
      "geopolitical_war_room:supply_chain_analyst",
    ],
  },
  {
    themeKey: "macro.roleTheme.policy",
    refs: ["macro_strategy_forum:policy_analyst"],
  },
  {
    themeKey: "macro.roleTheme.rotation",
    refs: [
      "sector_rotation_team:prosperity_analyst",
      "sector_rotation_team:flow_analyst",
      "sector_rotation_team:rotation_strategist",
    ],
  },
  {
    themeKey: "macro.roleTheme.allocation",
    refs: [
      "macro_strategy_forum:chief_strategist",
      "geopolitical_war_room:chief_strategist",
      "macro_rates_fx_desk:macro_pm",
      "etf_allocation_desk:macro_allocator",
    ],
  },
];

/** Flat list of all catalogued macro role refs (18). */
export const MACRO_ROLE_REFS: string[] = MACRO_ROLE_THEMES.flatMap(
  (theme) => theme.refs,
);

// ---------------------------------------------------------------------------
// Indicator board taxonomy
// ---------------------------------------------------------------------------

/**
 * One observed key indicator and the role that analyses it. The board keeps
 * only non-linear turning-point signals (leading / confirming indicators)
 * used in macro best practice (CFA macro framework, clock-style investing),
 * one role per indicator — no large linear data dashboard.
 */
export interface MacroBoardIndicator {
  /** i18n key of the indicator name (macro.board.ind.*). */
  nameKey: string;
  /** i18n key of the one-line observation hint (macro.board.ind.*Hint). */
  hintKey: string;
  /** Ref of the role responsible for this single indicator. */
  roleRef: string;
}

export interface MacroBoardCategory {
  /** i18n key of the category name (macro.board.cat.*). */
  nameKey: string;
  indicators: MacroBoardIndicator[];
}

/** Five categories, eleven tracked roles (9 indicators + 2 synthesis roles). */
export const MACRO_BOARD_CATEGORIES: MacroBoardCategory[] = [
  {
    nameKey: "macro.board.cat.growth",
    indicators: [
      {
        nameKey: "macro.board.ind.globalPmi",
        hintKey: "macro.board.ind.globalPmiHint",
        roleRef: "macro_strategy_forum:global_economist",
      },
      {
        nameKey: "macro.board.ind.domesticOutput",
        hintKey: "macro.board.ind.domesticOutputHint",
        roleRef: "macro_strategy_forum:domestic_economist",
      },
      {
        nameKey: "macro.board.ind.inventoryCycle",
        hintKey: "macro.board.ind.inventoryCycleHint",
        roleRef: "sector_rotation_team:cycle_analyst",
      },
    ],
  },
  {
    nameKey: "macro.board.cat.inflation",
    indicators: [
      {
        nameKey: "macro.board.ind.cpiPpi",
        hintKey: "macro.board.ind.cpiPpiHint",
        roleRef: "macro_rates_fx_desk:commodity_inflation_analyst",
      },
      {
        nameKey: "macro.board.ind.energyCommodity",
        hintKey: "macro.board.ind.energyCommodityHint",
        roleRef: "geopolitical_war_room:energy_analyst",
      },
    ],
  },
  {
    nameKey: "macro.board.cat.money",
    indicators: [
      {
        nameKey: "macro.board.ind.ratesCurve",
        hintKey: "macro.board.ind.ratesCurveHint",
        roleRef: "macro_rates_fx_desk:rates_analyst",
      },
      {
        nameKey: "macro.board.ind.policyLiquidity",
        hintKey: "macro.board.ind.policyLiquidityHint",
        roleRef: "macro_strategy_forum:policy_analyst",
      },
    ],
  },
  {
    nameKey: "macro.board.cat.external",
    indicators: [
      {
        nameKey: "macro.board.ind.fx",
        hintKey: "macro.board.ind.fxHint",
        roleRef: "macro_rates_fx_desk:fx_strategist",
      },
      {
        nameKey: "macro.board.ind.geopolitics",
        hintKey: "macro.board.ind.geopoliticsHint",
        roleRef: "geopolitical_war_room:geopolitical_analyst",
      },
    ],
  },
  {
    nameKey: "macro.board.cat.synthesis",
    indicators: [
      {
        nameKey: "macro.board.ind.macroAllocator",
        hintKey: "macro.board.ind.macroAllocatorHint",
        roleRef: "etf_allocation_desk:macro_allocator",
      },
      {
        nameKey: "macro.board.ind.macroAnalyst",
        hintKey: "macro.board.ind.macroAnalystHint",
        roleRef: "equity_research_team:macro_analyst",
      },
    ],
  },
];

/** Flat list of the nine indicator role refs. */
export const MACRO_BOARD_ROLE_REFS: string[] = MACRO_BOARD_CATEGORIES.flatMap(
  (category) => category.indicators.map((indicator) => indicator.roleRef),
);

/** Split a "preset:agent" ref into its parts. */
export function splitRoleRef(ref: string): { presetName: string; agentId: string } {
  const [presetName, agentId] = ref.split(":");
  return { presetName: presetName ?? "", agentId: agentId ?? "" };
}
