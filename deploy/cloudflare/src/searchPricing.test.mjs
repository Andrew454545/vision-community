import assert from "node:assert/strict";
import test from "node:test";
import { searchCost } from "./searchPricing.js";

test("only an explicit positive decimal operator price can replace the historical default", () => {
  assert.equal(searchCost({}), 100000);
  for (const [value, expected] of [["1", 1], ["100", 100], ["250000", 250000],
    [String(Number.MAX_SAFE_INTEGER), Number.MAX_SAFE_INTEGER]]) {
    assert.equal(searchCost({ SEARCH_COST_UNITS: value }), expected);
  }
  for (const value of [null, true, 100, "", "0", "-1", "01", "100.0", "1e2", " 100", "100 ",
    "Infinity", "NaN", "9007199254740992", "9".repeat(10000)]) {
    assert.equal(searchCost({ SEARCH_COST_UNITS: value }), null);
  }
});
