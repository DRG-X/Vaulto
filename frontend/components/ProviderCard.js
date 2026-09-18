import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import CostBar from "./CostBar";
import { saveComparison } from "../lib/api";
import {
  providerUrl, providerIcon, providerSlug, providerNote,
} from "../lib/providerMeta";
import {
  money, rate as fmtRate, eta, railLabel, categoryLabel, percent, DASH,
} from "../lib/format";

/**
 * ProviderCard — one provider's quote.
 *
 * Props:
 *   quote      object  — a row from /api/rates results[]
 *   rank       number  — 1-based position under the ACTIVE sort
 *   badges     string[]— which sort modes this provider wins ("cheapest", …)
 *   onAlert    fn
 *   ratesData  object  — full response, for the save payload
 */
export default function ProviderCard({ quote, rank, badges = [], onAlert, ratesData }) {
  const { isSignedIn, getToken } = useAuth();
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);

  const slug = providerSlug(quote.provider);
  const url = providerUrl(quote.provider);
  const note = providerNote(quote);
  const payIn = railLabel(quote.pay_in_method);
  const payOut = railLabel(quote.pay_out_method);

  const handleSave = async () => {
    if (!isSignedIn || saving || saved) return;
    setSaving(true);
    try {
      const token = await getToken();
      await saveComparison(token, {
        amount: quote.send_amount,
        from_currency: quote.currency_from,
        to_currency: quote.currency_to,
        results_json: JSON.stringify(ratesData?.results || []),
      });
      setSaved(true);
    } catch {
      // Non-critical — the comparison is still on screen.
    } finally {
      setSaving(false);
    }
  };

  const handleProviderClick = async () => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const headers = { "Content-Type": "application/json" };
    if (isSignedIn) {
      try {
        const token = await getToken();
        if (token) headers["Authorization"] = "Bearer " + token;
      } catch (_) {}
    }
    fetch(apiUrl + "/api/clicks", {
      method: "POST",
      headers,
      body: JSON.stringify({
        provider: quote.provider,
        from_currency: quote.currency_from,
        to_currency: quote.currency_to,
        amount: quote.send_amount,
      }),
    }).catch(() => {});
  };

  return (
    <div className={`pc-card ${badges.length ? "pc-winner" : ""} ${quote.avoid ? "pc-avoid" : ""}`}>
      {/* ── Header ── */}
      <div className="pc-header">
        <div className="pc-left">
          <span className={`rank-badge rank-${Math.min(rank, 3)}`}>{rank}</span>
          <div>
            <div className="pc-name">
              <span className="pc-icon" aria-hidden="true">{providerIcon(quote)}</span>
              {quote.provider}
            </div>
            <div className="pc-tags">
              {quote.category && <span className="tag">{categoryLabel(quote.category)}</span>}
              {quote.avoid && <span className="tag tag-avoid">⚠ Expensive</span>}
              {quote.is_promotional && <span className="tag tag-promo">Promo rate</span>}
              {quote.rate_type === "scraped" && <span className="tag tag-soft">Indicative</span>}
            </div>
          </div>
        </div>

        <div className="pc-receive">
          <div className="pc-receive-label">Recipient gets</div>
          <div className="pc-receive-amount">
            {money(quote.receive_amount, quote.currency_to)}
            <span className="pc-receive-ccy"> {quote.currency_to}</span>
          </div>
        </div>
      </div>

      {/* ── Winner badges: which sort modes this provider tops ── */}
      {badges.length > 0 && (
        <div className="pc-badges">
          {badges.map((b) => (
            <span key={b} className="badge">{BADGE_LABELS[b] || b}</span>
          ))}
        </div>
      )}

      {/* ── True cost ── */}
      <div className="pc-cost">
        <CostBar quote={quote} />
      </div>

      {/* ── Meta row ── */}
      <div className="pc-meta">
        <div className="pc-meta-item">
          <span className="pc-meta-label">Rate</span>
          <span className="pc-meta-val" title={quote.exchange_rate_exact || undefined}>
            {fmtRate(quote.exchange_rate)}
          </span>
        </div>
        <div className="pc-meta-item">
          <span className="pc-meta-label">Upfront fee</span>
          <span className="pc-meta-val">
            {money(quote.fee, quote.currency_from)} {quote.currency_from}
          </span>
        </div>
        <div className="pc-meta-item">
          <span className="pc-meta-label">Arrives</span>
          <span className="pc-meta-val">{eta(quote)}</span>
        </div>
        {payOut && (
          <div className="pc-meta-item">
            <span className="pc-meta-label">Delivery</span>
            <span className="pc-meta-val">{payOut}</span>
          </div>
        )}
      </div>

      {note && <p className="pc-note">{note}</p>}

      {/* ── Actions ── */}
      <div className="pc-actions">
        <button
          className="btn-ghost-sm"
          onClick={() => setDetailOpen((v) => !v)}
          aria-expanded={detailOpen}
          id={`detail-${slug}`}
        >
          {detailOpen ? "Hide details" : "Details"}
        </button>

        {isSignedIn && (
          <button className="btn-ghost-sm" onClick={handleSave} disabled={saving || saved} id={`save-${slug}`}>
            {saved ? "✓ Saved" : saving ? "Saving…" : "💾 Save"}
          </button>
        )}

        {isSignedIn ? (
          <button className="btn-ghost-sm" onClick={() => onAlert && onAlert(quote)} id={`alert-${slug}`}>
            🔔 Alert
          </button>
        ) : (
          <Link href="/auth?mode=signup" className="btn-ghost-sm pc-link-btn" id={`alert-${slug}`}>
            🔔 Alert
          </Link>
        )}

        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className={badges.length ? "pc-cta-primary" : "pc-cta-ghost"}
            id={`send-${slug}`}
            onClick={handleProviderClick}
          >
            Send with {quote.provider} →
          </a>
        ) : (
          // No known link. Sending someone from a money-transfer comparison to
          // a guessed URL is worse than sending them nowhere.
          <span className="pc-cta-none">Rate shown for comparison</span>
        )}
      </div>

      {/* ── Detail drawer ── */}
      {detailOpen && (
        <dl className="pc-detail">
          <div><dt>You send</dt><dd>{money(quote.send_amount, quote.currency_from)} {quote.currency_from}</dd></div>
          <div><dt>Converted</dt><dd>{money(quote.principal_amount, quote.currency_from)} {quote.currency_from}</dd></div>
          <div><dt>Exact rate</dt><dd className="mono">{quote.exchange_rate_exact || DASH}</dd></div>
          <div><dt>Exact received</dt><dd className="mono">{quote.receive_amount_exact || DASH}</dd></div>
          <div><dt>Mid-market</dt><dd>{quote.mid_market_rate != null ? fmtRate(quote.mid_market_rate) : DASH}</dd></div>
          <div><dt>Rate markup</dt><dd>{percent(quote.fx_markup_pct)}</dd></div>
          {payIn && <div><dt>Funded by</dt><dd>{payIn}</dd></div>}
          {quote.service_name && <div><dt>Service</dt><dd>{quote.service_name}</dd></div>}
          <div>
            <dt>Figure source</dt>
            <dd>
              {/* Whether the figure is the provider's own or one we derived by
                  re-basing their quote onto the fee-inclusive basis. Worth
                  saying: it is the difference between a quoted price and a
                  computed one. */}
              {quote.normalized
                ? "Re-based by Vaulto to a fee-inclusive basis"
                : "As published by the provider"}
            </dd>
          </div>
          <div>
            <dt>Fee model</dt>
            <dd>
              {quote.fee_model === "deducted"
                ? "Taken from the amount you send"
                : quote.fee_model === "added"
                ? "Charged on top of the amount converted"
                : DASH}
            </dd>
          </div>
        </dl>
      )}

      <style jsx>{`
        .pc-card {
          background: var(--surface-float);
          border-radius: var(--radius-lg);
          padding: 1.5rem;
          box-shadow: var(--shadow-sm);
          transition: box-shadow 0.2s, transform 0.15s;
        }
        .pc-card:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
        .pc-winner { box-shadow: 0 0 0 2px var(--secondary), var(--shadow-md); }
        .pc-avoid { opacity: 0.92; }

        .pc-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: 0.85rem; }
        .pc-left { display: flex; align-items: flex-start; gap: 0.75rem; }
        .pc-name {
          font-family: var(--font-display); font-weight: 700; font-size: 1.1rem;
          color: var(--text); display: flex; align-items: center; gap: 0.4rem;
        }
        .pc-icon { font-size: 0.95rem; }
        .pc-tags { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.3rem; }
        .tag {
          font-size: 0.65rem; font-weight: 600; padding: 0.1rem 0.45rem;
          border-radius: var(--radius-full); background: var(--surface-high);
          color: var(--text-mid);
        }
        .tag-avoid { background: var(--error-surface); color: var(--error); }
        .tag-promo { background: var(--tertiary-dim); color: var(--tertiary); }
        .tag-soft { background: var(--warn-surface); color: var(--warn); }

        .pc-receive { text-align: right; flex-shrink: 0; }
        .pc-receive-label { font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); margin-bottom: 0.2rem; }
        .pc-receive-amount { font-family: var(--font-display); font-size: 1.6rem; font-weight: 800; letter-spacing: -0.03em; color: var(--tertiary); line-height: 1; }
        .pc-receive-ccy { font-size: 0.7rem; font-weight: 600; color: var(--muted); }

        .pc-badges { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.85rem; }
        .badge {
          font-size: 0.68rem; font-weight: 700; padding: 0.18rem 0.6rem;
          border-radius: var(--radius-full);
          background: var(--secondary-dim); color: var(--secondary);
        }

        .pc-cost { padding: 0.85rem 0; border-top: 1px solid var(--surface-high); }

        .pc-meta {
          display: flex; gap: 1.5rem; flex-wrap: wrap;
          padding: 0.75rem 0;
          border-top: 1px solid var(--surface-high);
          border-bottom: 1px solid var(--surface-high);
          margin-bottom: 0.85rem;
        }
        .pc-meta-item { display: flex; flex-direction: column; gap: 0.15rem; }
        .pc-meta-label { font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
        .pc-meta-val { font-size: 0.9rem; font-weight: 600; color: var(--text-mid); }

        .pc-note { font-size: 0.78rem; color: var(--muted); margin-bottom: 0.85rem; line-height: 1.5; }

        .pc-actions { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
        .pc-link-btn { text-decoration: none; display: inline-flex; align-items: center; }
        .pc-cta-primary {
          margin-left: auto; display: inline-flex; align-items: center;
          background: var(--secondary); color: white;
          font-family: var(--font-display); font-weight: 700; font-size: 0.85rem;
          border-radius: var(--radius-md); padding: 0.55rem 1.1rem;
          text-decoration: none; border: none;
          transition: opacity 0.15s, transform 0.1s;
        }
        .pc-cta-primary:hover { opacity: 0.9; transform: translateY(-1px); }
        .pc-cta-ghost {
          margin-left: auto; display: inline-flex; align-items: center;
          background: transparent; color: var(--text-mid);
          font-weight: 500; font-size: 0.85rem;
          border: 1px solid var(--outline); border-radius: var(--radius-md);
          padding: 0.55rem 1.1rem; text-decoration: none;
          transition: border-color 0.15s, color 0.15s;
        }
        .pc-cta-ghost:hover { border-color: var(--secondary); color: var(--secondary); }
        .pc-cta-none { margin-left: auto; font-size: 0.78rem; color: var(--muted); font-style: italic; }

        .pc-detail {
          margin-top: 1rem; padding-top: 1rem;
          border-top: 1px solid var(--surface-high);
          display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 0.65rem 1.25rem;
        }
        .pc-detail div { display: flex; flex-direction: column; gap: 0.1rem; }
        .pc-detail dt { font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
        .pc-detail dd { font-size: 0.85rem; color: var(--text-mid); }
        .mono { font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }

        @media (max-width: 560px) {
          .pc-header { flex-direction: column; }
          .pc-receive { text-align: left; }
          .pc-cta-primary, .pc-cta-ghost, .pc-cta-none { margin-left: 0; width: 100%; justify-content: center; }
        }
      `}</style>
    </div>
  );
}

const BADGE_LABELS = {
  cheapest: "🏆 Cheapest",
  fastest: "⚡ Fastest",
  lowest_fee: "🪙 Lowest fee",
  best_rate: "📈 Best rate",
  best_value: "⭐ Best value",
};
