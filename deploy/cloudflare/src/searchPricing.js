import { SEARCH_COST } from "./model.js";

// Operator configuration only; never derive the charge from browser input.
// Keep the historical default until a measured early-release price is selected.
export function searchCost(env) {
  const value = env.SEARCH_COST_UNITS;
  if (value === undefined) return SEARCH_COST;
  if (typeof value !== "string" || !/^[1-9][0-9]{0,15}$/.test(value)) return null;
  const cost = Number(value);
  return Number.isSafeInteger(cost) ? cost : null;
}

export function validSearchQuote(value) {
  return Number.isSafeInteger(value) && value > 0;
}
