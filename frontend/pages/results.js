import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useRouter } from "next/router";
import { useAuth } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";
import Nav from "../components/Nav";
import Footer from "../components/Footer";
import ProviderCard from "../components/ProviderCard";
import AlertModal from "../components/AlertModal";
import SortBar from "../components/SortBar";
import FilterPanel from "../components/FilterPanel";
import ProviderStatus, { MidMarketNote } from "../components/ProviderStatus";
import { getRates, SORT_MODES } from "../lib/api";
import { CURRENCIES } from "../lib/currencies";
import { money, percent, rate as fmtRate, eta } from "../lib/format";

/** Filter state as it lives in the URL, so a comparison is shareable. */
function filtersFromQuery(q) {
  return {
    maxEtaMinutes: q.speed || "",
    payOutMethod: q.payout || "",
    payInMethod: q.payin || "",
    includePromo: q.promo !== "0",
  };
}

function queryFromFilters(f) {
  const out = {};
  if (f.maxEtaMinutes) out.speed = f.maxEtaMinutes;
  if (f.payOutMethod) out.payout = f.payOutMethod;
  if (f.payInMethod) out.payin = f.payInMethod;
  if (f.includePromo === false) out.promo = "0";
  return out;
}

export default function Results() {
  const router = useRouter();
  const { isSignedIn } = useAuth();

  const { from = "AUD", to = "INR", amount = "1000" } = router.query;
  // Empty string is not a sort mode. Reading it as one would leave every pill
  // unhighlighted and send `sort_by=` upstream.
  const sort = router.query.sort || SORT_MODES.CHEAPEST;

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [alertTarget, setAlertTarget] = useState(null);
  const [alertOpen, setAlertOpen] = useState(false);
  const [showAvoid, setShowAvoid] = useState(false);

  const [formFrom, setFormFrom] = useState(from);
  const [formTo, setFormTo] = useState(to);
  const [formAmount, setFormAmount] = useState(amount);

  const filters = useMemo(() => filtersFromQuery(router.query), [router.query]);
  const refreshTimer = useRef(null);

  const fetchRates = useCallback(async () => {
    if (!from || !to || !amount) return;
    setLoading(true);
    setError("");
    try {
      // Sorting and filtering are SERVER-side: the backend chooses which of a
      // provider's pay-in/pay-out rails to quote based on the active filter,
      // which re-sorting rows in the browser cannot reproduce.
      const result = await getRates({
        from, to, amount: parseFloat(amount),
        sortBy: sort,
        maxEtaMinutes: filters.maxEtaMinutes || undefined,
        payOutMethod: filters.payOutMethod || undefined,
        payInMethod: filters.payInMethod || undefined,
        includePromo: filters.includePromo,
      });
      setData(result);
    } catch (e) {
      setError(e.message || "Failed to fetch rates. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [
    from, to, amount, sort,
    filters.maxEtaMinutes, filters.payOutMethod, filters.payInMethod, filters.includePromo,
  ]);

  useEffect(() => {
    if (!router.isReady) return;
    setFormFrom(from);
    setFormTo(to);
    setFormAmount(amount);
    fetchRates();
  }, [router.isReady, fetchRates]);

  useEffect(() => {
    refreshTimer.current = setInterval(() => {
      if (data?.stale) fetchRates();
    }, 30000);
    return () => clearInterval(refreshTimer.current);
  }, [data?.stale, fetchRates]);

  const pushQuery = (patch) => {
    const query = {
      from, to, amount,
      ...(sort !== SORT_MODES.CHEAPEST ? { sort } : {}),
      ...queryFromFilters(filters),
      ...patch,
    };
    // Next stringifies an `undefined` value to "" and still emits the key, so
    // `?sort=` would survive and `router.query.sort` would be "" — never the
    // destructuring default. Strip empties instead of relying on that.
    for (const key of Object.keys(query)) {
      if (query[key] === undefined || query[key] === "") delete query[key];
    }
    router.push({ pathname: "/results", query });
  };

  const handleSearch = (e) => {
    e.preventDefault();
    const p = parseFloat(formAmount);
    if (!p || p <= 0 || formFrom === formTo) return;
    router.push({
      pathname: "/results",
      query: {
        from: formFrom, to: formTo, amount: p,
        ...(sort !== SORT_MODES.CHEAPEST ? { sort } : {}),
        ...queryFromFilters(filters),
      },
    });
  };

  const handleSort = (next) =>
    pushQuery(next === SORT_MODES.CHEAPEST ? { sort: undefined } : { sort: next });

  const handleFilters = (next) => {
    const cleared = { speed: undefined, payout: undefined, payin: undefined, promo: undefined };
    pushQuery({ ...cleared, ...queryFromFilters(next) });
  };

  const handleAlert = (provider) => {
    if (!isSignedIn) {
      // Bring them back to this exact comparison afterwards, rather than
      // dropping them on a dashboard and making them rebuild it.
      router.push(`/auth?mode=signup&redirect_url=${encodeURIComponent(router.asPath)}`);
      return;
    }
    setAlertTarget(provider);
    setAlertOpen(true);
  };

  // The backend already returns rows ordered by the active sort, and keeps
  // failed providers out of `results` entirely.
  const results = data?.results || [];

  // Banks are separated out, not hidden: they are in the comparison precisely
  // to show the gap, but ranking them alongside fintechs buries the useful
  // options. `avoid` is the backend's own flag, not a client-side guess.
  const mainResults = results.filter((r) => !r.avoid);
  const avoidResults = results.filter((r) => r.avoid);

  const best = mainResults[0] || results[0];

  /** Which sort modes each provider wins, from the backend's own badges. */
  const badgesFor = (name) =>
    Object.entries(data?.best_by || {})
      .filter(([, winner]) => winner === name)
      .map(([mode]) => mode);

  // Computed by receive amount, not list position: the rows are ordered by
  // the ACTIVE sort, so under "fastest" or "lowest fee" the last bank in the
  // list is not the worst-paying one and the gap would be understated.
  const byReceive = (a, b) => a.receive_amount - b.receive_amount;
  const bestPaying = mainResults.length
    ? [...mainResults].sort(byReceive).at(-1)
    : null;
  const worstAvoid = avoidResults.length ? [...avoidResults].sort(byReceive)[0] : null;
  const bankGap =
    bestPaying && worstAvoid ? bestPaying.receive_amount - worstAvoid.receive_amount : null;

  const fromFlag = CURRENCIES.find((c) => c.code === from)?.flag || "";
  const toFlag = CURRENCIES.find((c) => c.code === to)?.flag || "";

  return (
    <>
      <Head>
        {/* One template string, not interpolated children: React warns that a
            <title> with multiple child nodes breaks hydration. */}
        <title>{`Compare ${from} → ${to} — Vaulto Live Rates`}</title>
        <meta
          name="description"
          content={`Compare live ${from} to ${to} transfer costs across banks, fintechs and brokers. True cost including exchange-rate markup.`}
        />
      </Head>

      <Nav variant="light" />

      <section className="results-header">
        <div className="container">
          <p className="label-sm" style={{ color: "var(--secondary)", marginBottom: "0.5rem" }}>
            Live comparison
          </p>
          <div className="results-title-row">
            <h1 className="display-md">
              Send {fromFlag} {from} → {toFlag} {to}
            </h1>
            {data?.cached && <span className="pill pill-muted" style={{ alignSelf: "center" }}>⚡ Cached</span>}
            {data?.stale && (
              <span className="pill" style={{ alignSelf: "center", background: "var(--warn-surface)", color: "var(--warn)" }}>
                ⏰ Stale
              </span>
            )}
          </div>

          <form onSubmit={handleSearch} className="results-form card" style={{ marginTop: "1.5rem" }}>
            <div className="results-form-fields">
              <div className="field">
                <label htmlFor="rf-amount">Amount</label>
                <input id="rf-amount" type="number" min="1" value={formAmount} onChange={(e) => setFormAmount(e.target.value)} placeholder="1000" />
              </div>
              <div className="field">
                <label htmlFor="rf-from">You send</label>
                <select id="rf-from" value={formFrom} onChange={(e) => setFormFrom(e.target.value)}>
                  {CURRENCIES.map((c) => <option key={c.code} value={c.code}>{c.flag} {c.code}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="rf-to">Recipient gets</label>
                <select id="rf-to" value={formTo} onChange={(e) => setFormTo(e.target.value)}>
                  {CURRENCIES.map((c) => <option key={c.code} value={c.code}>{c.flag} {c.code}</option>)}
                </select>
              </div>
              <div className="field">
                <label>&nbsp;</label>
                <button type="submit" className="btn-secondary">Compare →</button>
              </div>
            </div>
          </form>
        </div>
      </section>

      <div className="container results-layout">
        <main className="results-main">
          {error && (
            <div className="error-box" style={{ marginBottom: "1rem" }}>
              ⚠️ {error}
              <button onClick={fetchRates} className="retry-link">Retry</button>
            </div>
          )}

          {loading ? (
            <>
              <div className="loading-box"><div className="spinner" /><p>Comparing 28 providers…</p></div>
              {[1, 2, 3].map((i) => (
                <div key={i} className="card" style={{ marginBottom: "1rem", padding: "1.5rem" }}>
                  <div className="skeleton-line" style={{ width: "40%", marginBottom: "0.75rem" }} />
                  <div className="skeleton-line" style={{ width: "60%", marginBottom: "0.5rem" }} />
                  <div className="skeleton-line" style={{ width: "30%" }} />
                </div>
              ))}
            </>
          ) : (
            <>
              {best && !error && (
                <div className="best-card anim-fade-up" style={{ marginBottom: "1.25rem" }}>
                  <div>
                    <div className="best-badge">⭐ Best under “{SORT_LABELS[sort] || "Cheapest"}”</div>
                    <div className="best-provider-name">{best.provider}</div>
                    <div className="best-meta">
                      <span>Rate: {fmtRate(best.exchange_rate)}</span>
                      {best.total_cost != null && (
                        <span>True cost: {money(best.total_cost, best.currency_from)} {best.currency_from}</span>
                      )}
                      <span>{eta(best)}</span>
                    </div>
                    {/* savings_vs_worst is max-minus-min receive, so it belongs
                        to the best-PAYING provider. Under "fastest" or "lowest
                        fee" the headline card is someone else, and crediting
                        them with a saving they do not deliver is simply wrong. */}
                    {data?.savings_vs_worst > 0 && bestPaying?.provider === best.provider && (
                      <div className="savings-pill">
                        💰 {money(data.savings_vs_worst, best.currency_to)} {best.currency_to} more than the worst option here
                        {/* vs the average is the more honest everyday number:
                            most people would not otherwise have picked the
                            single worst provider. */}
                        {data.savings_vs_average > 0 && (
                          <span className="savings-avg">
                            {" · "}{money(data.savings_vs_average, best.currency_to)} above average
                          </span>
                        )}
                      </div>
                    )}
                    {data?.savings_vs_worst > 0 && bestPaying && bestPaying.provider !== best.provider && (
                      <div className="savings-note">
                        {bestPaying.provider} pays the most here —{" "}
                        {money(bestPaying.receive_amount - best.receive_amount, best.currency_to)}{" "}
                        {best.currency_to} more than this option
                      </div>
                    )}
                  </div>
                  <div className="best-receive">
                    <div className="best-receive-label">Recipient gets</div>
                    <div className="best-receive-amount">{money(best.receive_amount, best.currency_to)}</div>
                    <div className="best-receive-currency">{best.currency_to}</div>
                  </div>
                </div>
              )}

              <MidMarketNote data={data} />

              {results.length > 0 && (
                <div style={{ marginTop: "1rem" }}>
                  <SortBar value={sort} onChange={handleSort} winners={data?.best_by} disabled={loading} />
                  <FilterPanel filters={filters} onChange={handleFilters} disabled={loading} />
                </div>
              )}

              <div className="provider-list">
                {mainResults.map((p, i) => (
                  <ProviderCard
                    key={`${p.provider}-${p.pay_in_method || ""}-${p.pay_out_method || ""}`}
                    quote={p}
                    rank={i + 1}
                    badges={badgesFor(p.provider)}
                    onAlert={handleAlert}
                    ratesData={data}
                  />
                ))}
              </div>

              {/* ── Banks: real quotes, not estimates ────────────────────── */}
              {avoidResults.length > 0 && (
                <>
                  <button className="avoid-toggle-btn" onClick={() => setShowAvoid((v) => !v)} id="avoid-toggle">
                    🏦 {showAvoid ? "Hide" : "Show"} {avoidResults.length} bank
                    {avoidResults.length === 1 ? "" : "s"} and legacy provider
                    {avoidResults.length === 1 ? "" : "s"}
                    {bankGap > 0 && (
                      <span className="avoid-gap">
                        {" "}— up to {money(bankGap, bestPaying.currency_to)} {bestPaying.currency_to} worse
                      </span>
                    )}
                    <span aria-hidden="true"> {showAvoid ? "▲" : "▼"}</span>
                  </button>

                  {showAvoid && (
                    <div className="avoid-section anim-fade-up">
                      <p className="avoid-intro">
                        These are live quotes on the same basis as everything above — the same
                        amount, fees included. They are separated out because they are
                        consistently the expensive option, not because the numbers are
                        different in kind.
                      </p>
                      <div className="provider-list">
                        {avoidResults.map((p, i) => (
                          <ProviderCard
                            key={`${p.provider}-${p.pay_out_method || ""}`}
                            quote={p}
                            rank={mainResults.length + i + 1}
                            badges={[]}
                            onAlert={handleAlert}
                            ratesData={data}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {results.length === 0 && !error && (
                <div className="empty-state card">
                  <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>📡</div>
                  <h3>No rates available</h3>
                  <p style={{ color: "var(--muted)", marginTop: "0.5rem" }}>
                    {data?.reason || "We couldn't fetch live rates for this corridor right now."}
                  </p>
                  <button className="btn-secondary" onClick={fetchRates} style={{ marginTop: "1rem" }}>
                    Try again
                  </button>
                </div>
              )}

              <ProviderStatus data={data} />

              <p className="results-disclaimer">
                Rates are indicative and fetched live from provider APIs and published rate
                pages. Quotes marked “Indicative” are read from a provider's public rate page
                and carry an estimated fee. Actual rates may differ at the time of transfer.
                Not financial advice.
              </p>
            </>
          )}
        </main>

        <aside className="results-sidebar">
          <div className="card" style={{ marginBottom: "1.5rem" }}>
            <p className="label-sm" style={{ marginBottom: "1rem" }}>💡 How to read this</p>
            <ul className="tips-list">
              <li><strong>True cost</strong> is the fee plus the markup hidden in the exchange rate — a “zero fee” transfer is rarely free.</li>
              <li><strong>Cheapest</strong> and <strong>Lowest fee</strong> often disagree. Cheapest is the one that matters.</li>
              <li>Filtering by speed switches a provider to its faster rail rather than removing it.</li>
              <li>Send on weekdays — some providers add a weekend surcharge.</li>
            </ul>
          </div>

          {!isSignedIn && (
            <div className="sidebar-cta">
              <p className="label-sm" style={{ color: "rgba(255,255,255,0.6)", marginBottom: "0.75rem" }}>🔔 Rate alerts</p>
              <h3 style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "1.2rem", color: "white", marginBottom: "0.5rem" }}>
                Never miss a great rate
              </h3>
              <p style={{ color: "rgba(255,255,255,0.6)", fontSize: "0.85rem", marginBottom: "1rem" }}>
                Create a free account to save comparisons and set WhatsApp alerts.
              </p>
              <Link
                href={`/auth?mode=signup&redirect_url=${encodeURIComponent(router.asPath)}`}
                className="btn-secondary"
                style={{ width: "100%", justifyContent: "center" }}
              >
                Create free account →
              </Link>
            </div>
          )}
        </aside>
      </div>

      <AlertModal
        isOpen={alertOpen}
        onClose={() => setAlertOpen(false)}
        onSuccess={() => setAlertOpen(false)}
        defaultFrom={alertTarget?.currency_from || from}
        defaultTo={alertTarget?.currency_to || to}
        defaultAmount={alertTarget?.send_amount || parseFloat(amount)}
      />

      <Footer />

      <style jsx>{`
        .results-header {
          background: var(--surface-low);
          padding: 2.5rem 0 0;
          border-bottom: 1px solid var(--surface-high);
        }
        .results-title-row { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
        .results-form-fields {
          display: grid;
          grid-template-columns: 1.4fr 1fr 1fr auto;
          gap: 0.75rem;
          align-items: end;
        }
        @media (max-width: 700px) { .results-form-fields { grid-template-columns: 1fr; } }
        .results-form { margin-bottom: 0; border-radius: var(--radius-lg) var(--radius-lg) 0 0; }

        .results-layout {
          display: grid;
          grid-template-columns: 1fr 320px;
          gap: 2rem;
          padding-top: 2rem;
          padding-bottom: 4rem;
          align-items: start;
        }
        @media (max-width: 900px) {
          .results-layout { grid-template-columns: 1fr; }
          .results-sidebar { order: -1; }
        }

        .retry-link {
          margin-left: 1rem; text-decoration: underline;
          background: none; border: none; color: inherit; cursor: pointer;
        }

        .provider-list { display: flex; flex-direction: column; gap: 1rem; }

        .tips-list { list-style: none; display: flex; flex-direction: column; gap: 0.75rem; }
        .tips-list li { font-size: 0.85rem; color: var(--text-mid); padding-left: 1rem; position: relative; line-height: 1.5; }
        .tips-list li::before { content: "→"; position: absolute; left: 0; color: var(--secondary); font-weight: 700; }

        .sidebar-cta {
          background: linear-gradient(135deg, var(--primary), #1e3460);
          border-radius: var(--radius-lg);
          padding: 1.5rem; position: relative; overflow: hidden;
        }
        .sidebar-cta::before {
          content: ""; position: absolute; top: -30px; right: -30px;
          width: 120px; height: 120px;
          background: radial-gradient(circle, var(--secondary), transparent);
          opacity: 0.15; border-radius: 50%;
        }

        .empty-state { text-align: center; padding: 3rem 1.5rem; }
        .empty-state h3 { font-family: var(--font-display); font-weight: 700; font-size: 1.1rem; }

        .savings-avg { opacity: 0.8; font-weight: 500; }
        .savings-note {
          margin-top: 0.6rem; font-size: 0.78rem;
          color: rgba(255, 255, 255, 0.7); line-height: 1.5;
        }
        .results-disclaimer { margin-top: 2rem; font-size: 0.75rem; color: var(--muted); line-height: 1.6; }

        .avoid-toggle-btn {
          background: var(--surface-float);
          border: 1px solid var(--outline);
          border-radius: var(--radius-md);
          padding: 0.75rem 1.25rem;
          font-family: var(--font-body); font-weight: 600; font-size: 0.875rem;
          color: var(--text-mid); cursor: pointer;
          width: 100%; text-align: left; margin-top: 1.5rem;
        }
        .avoid-toggle-btn:hover { border-color: var(--error); color: var(--error); }
        .avoid-gap { color: var(--error); font-weight: 700; }
        .avoid-section { margin-top: 1rem; display: flex; flex-direction: column; gap: 1rem; }
        .avoid-intro { font-size: 0.82rem; color: var(--muted); line-height: 1.6; }
      `}</style>
    </>
  );
}

const SORT_LABELS = {
  cheapest: "Cheapest",
  fastest: "Fastest",
  lowest_fee: "Lowest fee",
  best_rate: "Best rate",
  best_value: "Best value",
};
