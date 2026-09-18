import { useState } from "react";
import { rate as fmtRate, DASH } from "../lib/format";

/**
 * ProviderStatus — why some providers are not in the table.
 *
 * The backend reports three distinct reasons and this component keeps them
 * distinct, because they need three different responses from the reader:
 *
 *   unavailable  doesn't serve this corridor, this amount is outside its
 *                limits, or it needs an API key nobody has configured —
 *                nothing is wrong
 *   filtered     your own filter excluded it — relax the filter
 *   failed       it broke — that's on us
 *
 * Collapsing these into one "couldn't fetch rates from…" list, as the page
 * used to, makes a healthy system look broken and buries the one provider
 * that genuinely failed among twenty that were never going to appear.
 */
export default function ProviderStatus({ data }) {
  const [open, setOpen] = useState(false);

  const unavailable = data?.unavailable_providers || {};
  const filtered = data?.filtered_out || [];
  const failed = data?.failed_providers || [];
  const errors = (data?.errors || []).filter((q) => q?.error);

  const unavailableCount = Object.keys(unavailable).length;
  const total = unavailableCount + filtered.length + failed.length;
  if (total === 0) return null;

  return (
    <div className="ps">
      {/* Failures are the only category that needs attention, so they are the
          only one shown without being asked for. */}
      {failed.length > 0 && (
        <div className="ps-failed">
          <strong>Couldn't reach {failed.length} provider{failed.length === 1 ? "" : "s"}</strong>
          {/* The backend sends the reason per provider. A bare list of names
              says nothing actionable — "Wise: 503" and "SBI: page layout has
              probably changed" need very different responses. */}
          {errors.length > 0 ? (
            <ul className="ps-failed-list">
              {errors.map((q) => (
                <li key={q.provider}>
                  <span className="ps-failed-name">{q.provider}</span>
                  <span className="ps-failed-why">{q.error}</span>
                </li>
              ))}
            </ul>
          ) : (
            <span> — {failed.join(", ")}</span>
          )}
        </div>
      )}

      {filtered.length > 0 && (
        <div className="ps-filtered">
          <strong>{filtered.length} excluded by your filters:</strong> {filtered.join(", ")}
        </div>
      )}

      {unavailableCount > 0 && (
        <>
          <button
            type="button"
            className="ps-toggle"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            id="provider-status-toggle"
          >
            {unavailableCount} more provider{unavailableCount === 1 ? "" : "s"} not shown
            <span aria-hidden="true"> {open ? "▲" : "▼"}</span>
          </button>

          {open && (
            <ul className="ps-list">
              {Object.entries(unavailable)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([name, reason]) => (
                  <li key={name}>
                    <span className="ps-name">{name}</span>
                    <span className="ps-reason">{reason}</span>
                  </li>
                ))}
            </ul>
          )}
        </>
      )}

      <style jsx>{`
        .ps { display: flex; flex-direction: column; gap: 0.6rem; margin-top: 1.25rem; }
        .ps-failed, .ps-filtered {
          font-size: 0.82rem; line-height: 1.5;
          padding: 0.7rem 0.9rem; border-radius: var(--radius-md);
        }
        .ps-failed { background: var(--error-surface); color: var(--error); }
        .ps-failed-list {
          list-style: none; margin-top: 0.5rem;
          display: flex; flex-direction: column; gap: 0.3rem;
        }
        .ps-failed-list li { display: flex; gap: 0.5rem; flex-wrap: wrap; font-size: 0.78rem; }
        .ps-failed-name { font-weight: 600; min-width: 7rem; }
        .ps-failed-why { flex: 1; opacity: 0.85; }
        .ps-filtered { background: var(--surface-high); color: var(--text-mid); }
        .ps-toggle {
          align-self: flex-start;
          background: none; border: none; padding: 0; cursor: pointer;
          font-family: var(--font-body); font-size: 0.8rem; font-weight: 600;
          color: var(--muted); text-decoration: underline;
        }
        .ps-toggle:hover { color: var(--secondary); }
        .ps-list {
          list-style: none; display: flex; flex-direction: column; gap: 0.4rem;
          padding: 0.75rem 0.9rem; background: var(--surface-low);
          border-radius: var(--radius-md);
        }
        .ps-list li { display: flex; gap: 0.6rem; font-size: 0.78rem; flex-wrap: wrap; }
        .ps-name { font-weight: 600; color: var(--text-mid); min-width: 8rem; }
        .ps-reason { color: var(--muted); flex: 1; }
      `}</style>
    </div>
  );
}

/**
 * MidMarketNote — the reference rate every markup is measured against.
 *
 * Worth stating plainly: without it, "1.2% markup" is a number with no
 * denominator. When the backend could not find a reference it returns null,
 * and we say markup is unavailable rather than implying zero.
 */
export function MidMarketNote({ data }) {
  if (!data) return null;
  const midRate = data.mid_market_rate;
  const source = data.mid_market_source;

  if (midRate == null) {
    return (
      <p className="mm mm-none">
        No mid-market reference available for this corridor — rate markups are not shown.
        <style jsx>{`
          .mm { font-size: 0.78rem; line-height: 1.5; }
          .mm-none { color: var(--muted); }
        `}</style>
      </p>
    );
  }

  return (
    <p className="mm">
      Mid-market rate{" "}
      <strong title={data.mid_market_rate_exact || undefined}>{fmtRate(midRate)}</strong>
      {source && <span className="mm-src"> via {source}</span>} — every markup below is
      measured against it.
      <style jsx>{`
        .mm { font-size: 0.78rem; color: var(--text-mid); line-height: 1.5; }
        .mm strong { color: var(--text); font-variant-numeric: tabular-nums; }
        .mm-src { color: var(--muted); }
      `}</style>
    </p>
  );
}
