/**
 * Display metadata for every provider in the backend registry.
 *
 * The backend sends `category`, `priority` and `avoid` on each quote — the
 * facts that affect ranking. This file holds only presentation: the outbound
 * link, an icon and a brand colour.
 *
 * Deliberately NOT here: anything the backend already decides. Duplicating
 * "is this a bank" or "should this be avoided" in the client would let the two
 * disagree, and the client copy would be the stale one.
 */

const UTM = "utm_source=vaulto&utm_medium=comparison";

/**
 * Outbound links, by the exact provider name the backend returns.
 *
 * A missing entry is handled, not guessed: `providerUrl()` returns null and the
 * card renders a non-clickable state. Sending someone to a wrong or invented
 * URL from a money-transfer comparison is worse than sending them nowhere.
 */
const PROVIDER_LINKS = {
  // Priority 1 — Critical
  "Wise": "https://wise.com",
  "Remitly": "https://remitly.com",
  "XE": "https://xe.com",
  "CommBank": "https://www.commbank.com.au/personal/international/foreign-exchange-rates",
  "SBI": "https://www.sbi.co.in/web/personal-banking/information-services/forex-services",

  // Priority 2 — High
  "Western Union": "https://westernunion.com",
  "OFX": "https://www.ofx.com/en-au/",
  "InstaReM": "https://www.instarem.com/en-au/",
  "Airwallex": "https://www.airwallex.com/au",
  "Revolut": "https://revolut.com",
  "ANZ": "https://www.anz.com.au/personal/travel-international/foreign-exchange/",
  "Westpac": "https://www.westpac.com.au/personal-banking/foreign-exchange/",
  "HDFC Bank": "https://www.hdfcbank.com/personal/resources/rates",
  "ICICI Bank": "https://www.icicibank.com/personal-banking/forex",
  "BookMyForex": "https://www.bookmyforex.com/",
  "ExTravelMoney": "https://www.extravelmoney.com/",

  // Priority 3 — Medium
  "CurrencyFair": "https://www.currencyfair.com/",
  "WorldRemit": "https://www.worldremit.com/",
  "TorFX": "https://www.torfx.com/",
  "Niyo Global": "https://www.niyomoney.com/",
  "NAB": "https://www.nab.com.au/personal/international-banking",
  "MoneyGram": "https://www.moneygram.com/",
  "Thomas Cook India": "https://www.thomascook.in/foreign-exchange",
  "Axis Forex": "https://www.axisbank.com/forex",
  "Panda Remit": "https://www.pandaremit.com/",

  // Priority 4 — Low
  "SingX": "https://www.singx.co/",
  "Moneycorp": "https://www.moneycorp.com/",

  // Benchmark-only — never rendered, listed so the omission is intentional
  // rather than an oversight. The backend keeps it out of user-facing results.
  // "HOP Remit": intentionally absent.
};

/** Icons are per-category, not per-brand — no logos we do not have rights to. */
const CATEGORY_ICONS = {
  fintech: "⚡",
  bank: "🏦",
  neobank: "📱",
  legacy: "🌐",
  broker: "🤝",
  p2p: "🔄",
};

/**
 * Accent colour per category.
 *
 * Category, not per-provider identity: with 28 providers a unique hue each
 * would need a palette far past the point where colours stay distinguishable,
 * and rank already carries the ordering. These are the app's own tokens.
 */
const CATEGORY_COLORS = {
  fintech: "var(--secondary)",
  bank: "var(--error)",
  neobank: "var(--secondary)",
  legacy: "var(--warn)",
  broker: "var(--text-mid)",
  p2p: "var(--tertiary)",
};

export function providerUrl(name) {
  const base = PROVIDER_LINKS[name];
  if (!base) return null;
  return `${base}${base.includes("?") ? "&" : "?"}${UTM}`;
}

export function providerIcon(quote) {
  return CATEGORY_ICONS[quote?.category] || "💱";
}

export function providerColor(quote) {
  return CATEGORY_COLORS[quote?.category] || "var(--muted)";
}

/** Stable DOM-id fragment for a provider name. */
export function providerSlug(name) {
  return String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

/**
 * Why this provider is worth a second look, in one line.
 *
 * Only shown where the quote itself supports it — no editorial claims about
 * providers whose numbers do not back them up.
 */
export function providerNote(quote) {
  if (!quote) return null;
  if (quote.avoid) return "Banks typically charge far more than fintechs on this corridor";
  if (quote.is_promotional) return "Promotional rate — first transfer only, not repeatable";
  if (quote.category === "p2p") return "Peer-to-peer matching can beat the mid-market rate";
  if (quote.category === "broker") return "Dealer desk — better rates on larger transfers";
  if (quote.pay_out_method === "UPI") return "Pays out straight to UPI";
  if (quote.pay_out_method === "CASH_PICKUP") return "Recipient collects cash in person";
  return null;
}
