/**
 * Shared formatting for quote data.
 *
 * Two rules run through all of it:
 *
 * 1. **Never invent precision.** A field the backend omitted is rendered as
 *    "—", not as 0. `fx_markup_pct: null` means "no mid-market reference was
 *    available", which is a very different statement from "0% markup" — and
 *    printing 0% would flatter whichever provider happens to be listed.
 *
 * 2. **Never re-derive what the backend computed.** Total cost, markup and
 *    delivery windows all come back on the quote. Recomputing them here would
 *    reintroduce the float arithmetic the backend was fixed to avoid, and the
 *    two would drift apart.
 */

export const DASH = "—";

// ── Money & numbers ──────────────────────────────────────────────────────────

/** Currencies with no minor unit — showing them cents invents precision. */
const ZERO_DECIMAL = new Set([
  "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
  "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
]);
const THREE_DECIMAL = new Set(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"]);

export function currencyDecimals(code) {
  if (!code) return 2;
  const c = String(code).toUpperCase();
  if (ZERO_DECIMAL.has(c)) return 0;
  if (THREE_DECIMAL.has(c)) return 3;
  return 2;
}

/** Format an amount at its currency's real precision. */
export function money(value, currency) {
  if (value == null || Number.isNaN(Number(value))) return DASH;
  const d = currencyDecimals(currency);
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  }).format(Number(value));
}

/** Format with an explicit number of decimals (rates, percentages). */
export function num(value, decimals = 2) {
  if (value == null || Number.isNaN(Number(value))) return DASH;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Number(value));
}

/**
 * Exchange rates need more decimals than money.
 *
 * A rate below 1 (INR→AUD sits near 0.0179) loses all its meaning at 4dp, so
 * small rates get more places rather than being rounded into uselessness.
 */
export function rate(value) {
  if (value == null || Number.isNaN(Number(value))) return DASH;
  const v = Math.abs(Number(value));
  if (v === 0) return DASH;
  if (v < 0.01) return num(value, 6);
  if (v < 1) return num(value, 5);
  return num(value, 4);
}

export function percent(value, decimals = 2) {
  if (value == null || Number.isNaN(Number(value))) return DASH;
  return `${num(value, decimals)}%`;
}

// ── Delivery time ────────────────────────────────────────────────────────────

const MIN_PER_HOUR = 60;
const MIN_PER_DAY = 1440;

/**
 * Render the structured ETA range.
 *
 * Prefers the numeric window over `transfer_time`, because the prose label
 * also carries the payout rail ("2-3 business days (Bank Deposit)") and we
 * show that separately.
 */
export function eta(quote) {
  if (!quote) return DASH;
  const lo = quote.eta_min_minutes;
  const hi = quote.eta_max_minutes;
  if (lo == null && hi == null) return quote.transfer_time || DASH;

  const min = lo ?? hi;
  const max = hi ?? lo;
  const dayWord = quote.eta_is_business_days ? "business day" : "day";

  if (max <= 15) return "Within minutes";
  if (max < MIN_PER_HOUR) return `Within ${max} min`;
  if (max < MIN_PER_DAY) {
    const loH = Math.max(1, Math.round(min / MIN_PER_HOUR));
    const hiH = Math.max(1, Math.round(max / MIN_PER_HOUR));
    return loH === hiH ? `~${hiH} hour${hiH === 1 ? "" : "s"}` : `${loH}–${hiH} hours`;
  }
  const loD = Math.max(1, Math.round(min / MIN_PER_DAY));
  const hiD = Math.max(1, Math.round(max / MIN_PER_DAY));
  return loD === hiD
    ? `~${hiD} ${dayWord}${hiD === 1 ? "" : "s"}`
    : `${loD}–${hiD} ${dayWord}s`;
}

/** Sort key for "soonest first"; unknown timing sorts last, never first. */
export function etaMinutes(quote) {
  if (!quote) return Number.MAX_SAFE_INTEGER;
  return quote.eta_max_minutes ?? quote.eta_min_minutes ?? Number.MAX_SAFE_INTEGER;
}

// ── Rails & labels ───────────────────────────────────────────────────────────

const RAIL_LABELS = {
  BANK: "Bank transfer",
  BANK_TRANSFER: "Bank transfer",
  BANK_DEPOSIT: "Bank deposit",
  ACH: "Bank debit",
  DEBIT: "Debit card",
  DEBIT_CARD: "Debit card",
  CREDIT: "Credit card",
  CREDIT_CARD: "Credit card",
  APPLE_PAY: "Apple Pay",
  PAYTO: "PayTo",
  SWIFT: "SWIFT",
  UPI: "UPI",
  CASH_PICKUP: "Cash pickup",
  MOBILE_WALLET: "Mobile wallet",
  DIRECT_TO_PHONE: "To phone",
  PUSH_TO_CARD: "To card",
  HOME_DELIVERY: "Home delivery",
};

export function railLabel(method) {
  if (!method) return null;
  const key = String(method).toUpperCase();
  return RAIL_LABELS[key] || titleCase(key.replace(/_/g, " "));
}

export function titleCase(text) {
  return String(text)
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const CATEGORY_LABELS = {
  fintech: "Fintech",
  bank: "Bank",
  neobank: "Neobank",
  legacy: "Legacy",
  broker: "Broker",
  p2p: "Peer-to-peer",
};

export function categoryLabel(category) {
  if (!category) return null;
  return CATEGORY_LABELS[category] || titleCase(category);
}

// ── Cost ─────────────────────────────────────────────────────────────────────

/**
 * Split a quote's true cost into its visible and hidden parts.
 *
 * This is the number the whole comparison turns on. A provider advertising
 * "zero fees" usually recovers it in the exchange rate, so `fee` alone ranks
 * providers dishonestly — total cost is `fee + fx_markup_cost`.
 *
 * Returns null when no mid-market reference was available: without one the
 * markup is genuinely unknown, and showing the fee as if it were the whole
 * cost would repeat the exact illusion this is meant to expose.
 */
export function costBreakdown(quote) {
  if (!quote || quote.total_cost == null) return null;

  const fee = Number(quote.fee) || 0;
  const markup = Number(quote.fx_markup_cost) || 0;
  const total = Number(quote.total_cost);
  if (!(total > 0)) {
    return { fee, markup, total, feeShare: 0, markupShare: 0, currency: quote.currency_from };
  }
  return {
    fee,
    markup,
    total,
    // Clamped: a P2P provider beating mid-market has a NEGATIVE markup, which
    // is real, but a bar cannot render a negative width.
    feeShare: Math.max(0, Math.min(100, (fee / total) * 100)),
    markupShare: Math.max(0, Math.min(100, (markup / total) * 100)),
    currency: quote.currency_from,
  };
}

/** True when this provider's rate is BETTER than mid-market (P2P matching). */
export function beatsMidMarket(quote) {
  return quote?.fx_markup_pct != null && Number(quote.fx_markup_pct) < 0;
}
