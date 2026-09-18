import { useState } from "react";

/**
 * FilterPanel — narrow the comparison.
 *
 * Every filter is applied SERVER-side. That matters most for speed: the
 * backend picks which of a provider's rails to quote, so "within an hour"
 * switches Western Union to its minutes-settled option instead of removing
 * Western Union from the table.
 */

const SPEED_OPTIONS = [
  { value: "", label: "Any speed" },
  { value: "60", label: "Within an hour" },
  { value: "1440", label: "Within a day" },
  { value: "4320", label: "Within 3 days" },
];

// Values are the CANONICAL rail names from backend providers/rails.py, which
// normalizes each provider's own vocabulary (Wise's "BANK_TRANSFER", Western
// Union's "BANK_DEPOSIT") to one name. Using a provider's raw spelling here
// would silently drop every provider that spells it differently.
const PAYOUT_OPTIONS = [
  { value: "", label: "Any delivery" },
  { value: "BANK_DEPOSIT", label: "Bank deposit" },
  { value: "UPI", label: "UPI" },
  { value: "CASH_PICKUP", label: "Cash pickup" },
  { value: "MOBILE_WALLET", label: "Mobile wallet" },
];

const PAYIN_OPTIONS = [
  { value: "", label: "Any funding" },
  { value: "BANK", label: "Bank transfer" },
  { value: "DEBIT", label: "Debit card" },
  { value: "CREDIT", label: "Credit card" },
];

export default function FilterPanel({ filters, onChange, disabled = false }) {
  const [open, setOpen] = useState(false);

  const activeCount =
    (filters.maxEtaMinutes ? 1 : 0) +
    (filters.payOutMethod ? 1 : 0) +
    (filters.payInMethod ? 1 : 0) +
    (filters.includePromo === false ? 1 : 0);

  const set = (patch) => onChange({ ...filters, ...patch });

  const reset = () =>
    onChange({ maxEtaMinutes: "", payOutMethod: "", payInMethod: "", includePromo: true });

  return (
    <div className="fp">
      <button
        type="button"
        className="fp-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        id="filters-toggle"
      >
        Filters
        {activeCount > 0 && <span className="fp-count">{activeCount}</span>}
        <span className="fp-caret" aria-hidden="true">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="fp-body">
          <div className="fp-row">
            <label className="fp-field">
              <span className="fp-label">Arrives</span>
              <select
                value={filters.maxEtaMinutes || ""}
                onChange={(e) => set({ maxEtaMinutes: e.target.value })}
                disabled={disabled}
                id="filter-speed"
              >
                {SPEED_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>

            <label className="fp-field">
              <span className="fp-label">Delivered by</span>
              <select
                value={filters.payOutMethod || ""}
                onChange={(e) => set({ payOutMethod: e.target.value })}
                disabled={disabled}
                id="filter-payout"
              >
                {PAYOUT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>

            <label className="fp-field">
              <span className="fp-label">Paid with</span>
              <select
                value={filters.payInMethod || ""}
                onChange={(e) => set({ payInMethod: e.target.value })}
                disabled={disabled}
                id="filter-payin"
              >
                {PAYIN_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="fp-row fp-row-end">
            <label className="fp-check">
              <input
                type="checkbox"
                checked={filters.includePromo !== false}
                onChange={(e) => set({ includePromo: e.target.checked })}
                disabled={disabled}
                id="filter-promo"
              />
              <span>
                Include promotional rates
                {/* Promos are real money but first-transfer only, so someone
                    comparing ongoing cost should be able to switch them off. */}
                <span className="fp-hint"> — first transfer only</span>
              </span>
            </label>

            {activeCount > 0 && (
              <button type="button" className="fp-reset" onClick={reset} disabled={disabled}>
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}

      <style jsx>{`
        .fp { margin-bottom: 1rem; }
        .fp-toggle {
          display: inline-flex; align-items: center; gap: 0.45rem;
          padding: 0.45rem 1rem;
          border-radius: var(--radius-md);
          border: 1px solid var(--outline);
          background: var(--surface-float);
          color: var(--text-mid);
          font-family: var(--font-body); font-size: 0.85rem; font-weight: 600;
          cursor: pointer;
        }
        .fp-toggle:hover { border-color: var(--secondary); color: var(--secondary); }
        .fp-count {
          background: var(--secondary); color: white;
          border-radius: var(--radius-full);
          font-size: 0.68rem; font-weight: 700;
          min-width: 1.15rem; height: 1.15rem;
          display: inline-flex; align-items: center; justify-content: center;
          padding: 0 0.3rem;
        }
        .fp-caret { font-size: 0.6rem; }

        .fp-body {
          margin-top: 0.75rem; padding: 1rem;
          background: var(--surface-float);
          border-radius: var(--radius-lg);
          box-shadow: var(--shadow-sm);
          display: flex; flex-direction: column; gap: 0.85rem;
        }
        .fp-row { display: flex; gap: 0.85rem; flex-wrap: wrap; }
        .fp-row-end { align-items: center; justify-content: space-between; }
        .fp-field { display: flex; flex-direction: column; gap: 0.25rem; flex: 1 1 160px; }
        .fp-label {
          font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase;
          color: var(--muted); font-weight: 600;
        }
        .fp-field select {
          padding: 0.5rem 0.65rem;
          border-radius: var(--radius-md);
          border: 1px solid var(--outline);
          background: var(--surface-float);
          color: var(--text); font-size: 0.85rem; font-family: var(--font-body);
        }
        .fp-check { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: var(--text-mid); cursor: pointer; }
        .fp-hint { color: var(--muted); }
        .fp-reset {
          background: none; border: none; cursor: pointer;
          color: var(--secondary); font-size: 0.8rem; font-weight: 600;
          text-decoration: underline; font-family: var(--font-body);
        }
        @media (max-width: 560px) {
          .fp-row { flex-direction: column; }
        }
      `}</style>
    </div>
  );
}
