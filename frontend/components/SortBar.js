import { SORT_MODES } from "../lib/api";

/**
 * SortBar — the five ways to rank a comparison.
 *
 * These are not five orderings of the same answer. "Cheapest" and "Lowest fee"
 * routinely disagree, because a zero-fee provider can be the expensive one once
 * its rate markup is counted — and the backend selects a different pay-in/
 * pay-out rail per mode, so "Fastest" can switch a provider to its
 * minutes-settled option rather than dropping it.
 *
 * That is why changing sort re-queries rather than re-sorting in place.
 */
const OPTIONS = [
  { key: SORT_MODES.CHEAPEST,   label: "Cheapest",   hint: "Most money received" },
  { key: SORT_MODES.FASTEST,    label: "Fastest",    hint: "Earliest arrival" },
  { key: SORT_MODES.BEST_RATE,  label: "Best rate",  hint: "Smallest markup over mid-market" },
  { key: SORT_MODES.LOWEST_FEE, label: "Lowest fee", hint: "Smallest upfront fee" },
  { key: SORT_MODES.BEST_VALUE, label: "Best value", hint: "Cost and speed together" },
];

export default function SortBar({ value, onChange, winners = {}, disabled = false }) {
  return (
    <div className="sort-bar" role="group" aria-label="Sort results by">
      {OPTIONS.map((opt) => {
        const active = value === opt.key;
        const winner = winners[opt.key];
        return (
          <button
            key={opt.key}
            type="button"
            className={`sort-pill ${active ? "sort-active" : ""}`}
            onClick={() => onChange(opt.key)}
            disabled={disabled}
            aria-pressed={active}
            title={opt.hint}
            id={`sort-${opt.key}`}
          >
            <span className="sort-label">{opt.label}</span>
            {/* Naming the winner up front means the value of switching is
                visible before you switch. */}
            {winner && <span className="sort-winner">{winner}</span>}
          </button>
        );
      })}

      <style jsx>{`
        .sort-bar { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
        .sort-pill {
          display: flex; flex-direction: column; align-items: flex-start; gap: 0.1rem;
          padding: 0.45rem 1rem;
          border-radius: var(--radius-md);
          font-family: var(--font-body);
          border: 1px solid var(--outline);
          background: var(--surface-float);
          color: var(--text-mid);
          cursor: pointer;
          transition: background 0.15s, color 0.15s, border-color 0.15s;
          text-align: left;
        }
        .sort-pill:hover:not(:disabled) { border-color: var(--secondary); color: var(--secondary); }
        .sort-pill:disabled { opacity: 0.6; cursor: default; }
        .sort-label { font-size: 0.85rem; font-weight: 600; }
        .sort-winner { font-size: 0.68rem; color: var(--muted); font-weight: 500; }
        .sort-active {
          background: var(--secondary); color: white; border-color: var(--secondary);
        }
        .sort-active .sort-winner { color: rgba(255, 255, 255, 0.75); }
        .sort-active:hover:not(:disabled) { color: white; }
      `}</style>
    </div>
  );
}
