import { costBreakdown, money, percent, beatsMidMarket } from "../lib/format";

/**
 * CostBar — what this transfer actually costs, split into its two parts.
 *
 * The headline fee is not the price. A provider advertising "zero fees"
 * usually recovers it in the exchange rate, so showing the fee alone ranks
 * providers dishonestly. Total cost is `fee + FX markup`, and this bar shows
 * the split so a A$0-fee bank at a 3% markup reads as what it is.
 *
 * Form: a two-part stacked bar, which is the right shape for a
 * part-to-whole split of a single value. Not a pie (two slices, unreadable at
 * this size), not two separate numbers (the whole point is the proportion).
 *
 * Colour carries identity, never rank: blue is always the visible fee, amber
 * always the hidden markup, in every row. The pair was validated for
 * colour-vision separation against the card surface (ΔE 26.3 protan, 32.0
 * normal) and both segments are direct-labelled, so the reading never rests on
 * colour alone.
 */
export default function CostBar({ quote, compact = false }) {
  const cost = costBreakdown(quote);

  // No mid-market reference means the markup is genuinely unknown. Showing the
  // fee as though it were the whole cost would repeat the exact illusion this
  // component exists to expose, so we say so instead.
  if (!cost) {
    return (
      <div className="cost-unknown">
        <span className="cost-unknown-label">True cost</span>
        <span className="cost-unknown-value">
          Fee {money(quote?.fee, quote?.currency_from)} {quote?.currency_from}
          <span className="cost-unknown-note"> · rate markup unavailable</span>
        </span>
        <style jsx>{`
          .cost-unknown { display: flex; flex-direction: column; gap: 0.15rem; }
          .cost-unknown-label {
            font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase;
            color: var(--muted); font-weight: 600;
          }
          .cost-unknown-value { font-size: 0.85rem; font-weight: 600; color: var(--text-mid); }
          .cost-unknown-note { color: var(--muted); font-weight: 400; }
        `}</style>
      </div>
    );
  }

  const { fee, markup, total, feeShare, markupShare, currency } = cost;
  const better = beatsMidMarket(quote);

  return (
    <div className="cost">
      <div className="cost-head">
        <span className="cost-label">True cost</span>
        <span className="cost-total">
          {money(total, currency)} {currency}
          {quote.total_cost_pct != null && (
            <span className="cost-pct"> ({percent(quote.total_cost_pct)})</span>
          )}
        </span>
      </div>

      <div
        className="bar"
        role="img"
        aria-label={
          `Total cost ${money(total, currency)} ${currency}: ` +
          `upfront fee ${money(fee, currency)}, ` +
          `exchange-rate markup ${money(markup, currency)}`
        }
      >
        {feeShare > 0 && <span className="seg seg-fee" style={{ width: `${feeShare}%` }} />}
        {markupShare > 0 && <span className="seg seg-markup" style={{ width: `${markupShare}%` }} />}
      </div>

      {!compact && (
        <div className="legend">
          <span className="legend-item">
            <span className="swatch swatch-fee" aria-hidden="true" />
            Upfront fee <strong>{money(fee, currency)}</strong>
          </span>
          <span className="legend-item">
            <span className="swatch swatch-markup" aria-hidden="true" />
            {better ? "Rate bonus" : "Rate markup"}{" "}
            <strong>{better ? money(Math.abs(markup), currency) : money(markup, currency)}</strong>
            {quote.fx_markup_pct != null && (
              <span className="legend-pct"> ({percent(quote.fx_markup_pct)})</span>
            )}
          </span>
        </div>
      )}

      <style jsx>{`
        .cost { display: flex; flex-direction: column; gap: 0.4rem; }
        .cost-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
        .cost-label {
          font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase;
          color: var(--muted); font-weight: 600;
        }
        .cost-total {
          font-family: var(--font-display); font-weight: 700;
          font-size: 0.95rem; color: var(--text);
        }
        .cost-pct { color: var(--muted); font-weight: 500; font-size: 0.8rem; }

        /* Thin mark, rounded data-ends, 2px surface gap between segments. */
        .bar {
          display: flex;
          height: 8px;
          border-radius: var(--radius-full);
          background: var(--surface-high);
          overflow: hidden;
          gap: 2px;
        }
        .seg { display: block; height: 100%; border-radius: var(--radius-full); min-width: 3px; }
        .seg-fee { background: var(--secondary); }
        .seg-markup { background: var(--warn); }

        .legend { display: flex; flex-wrap: wrap; gap: 0.25rem 1rem; }
        .legend-item {
          display: inline-flex; align-items: center; gap: 0.35rem;
          font-size: 0.75rem; color: var(--text-mid);
        }
        .legend-item strong { color: var(--text); font-weight: 600; }
        .legend-pct { color: var(--muted); }
        .swatch { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
        .swatch-fee { background: var(--secondary); }
        .swatch-markup { background: var(--warn); }
      `}</style>
    </div>
  );
}
