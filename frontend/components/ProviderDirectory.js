import { useEffect, useState } from "react";
import Link from "next/link";
import { listProviders } from "../lib/api";
import { money, categoryLabel, DASH } from "../lib/format";
import { providerIcon, providerUrl } from "../lib/providerMeta";

/**
 * ProviderDirectory — every provider the engine compares, from the registry.
 *
 * This page used to hardcode three providers while the backend ranked 28. A
 * client-side list does not just go stale, it goes stale INVISIBLY: nothing
 * breaks, the page simply omits options the engine is already quoting. So the
 * list comes from `/api/providers`, which is the same metadata the comparison
 * selects and ranks on.
 *
 * Providers are grouped by direction because the corridor is the first thing
 * that decides whether one is relevant to you at all — an Australian student
 * cannot use SBI, and their parents cannot use Wise's Australian entity.
 */

const INTEGRATION_LABELS = {
  public_api: "Live API",
  partner_api: "Partner API",
  partial_api: "Limited API",
  scrape: "Published rates",
};

function Badge({ children, tone = "default" }) {
  return (
    <span className={`badge badge-${tone}`}>
      {children}
      <style jsx>{`
        .badge {
          font-size: 0.65rem; font-weight: 600;
          padding: 0.12rem 0.5rem; border-radius: var(--radius-full);
          background: var(--surface-high); color: var(--text-mid);
          white-space: nowrap;
        }
        .badge-avoid { background: var(--error-surface); color: var(--error); }
        .badge-info { background: var(--secondary-dim); color: var(--secondary); }
        .badge-warn { background: var(--warn-surface); color: var(--warn); }
      `}</style>
    </span>
  );
}

function limitText(p) {
  if (p.min_amount == null && p.max_amount == null) return null;
  const unit = p.limits_currency || "";
  if (p.min_amount != null && p.max_amount != null) {
    return `${money(p.min_amount, unit)}–${money(p.max_amount, unit)} ${unit}`;
  }
  if (p.min_amount != null) return `From ${money(p.min_amount, unit)} ${unit}`;
  return `Up to ${money(p.max_amount, unit)} ${unit}`;
}

function ProviderRow({ provider }) {
  const url = providerUrl(provider.name);
  const limits = limitText(provider);

  return (
    <li className="row">
      <div className="row-main">
        <span className="row-icon" aria-hidden="true">
          {providerIcon({ category: provider.category })}
        </span>
        <div>
          <div className="row-name">
            <Link href={`/providers/${provider.slug}`}>{provider.name}</Link>
          </div>
          <div className="row-badges">
            <Badge>{categoryLabel(provider.category)}</Badge>
            <Badge tone={provider.integration === "scrape" ? "warn" : "info"}>
              {INTEGRATION_LABELS[provider.integration] || provider.integration}
            </Badge>
            {provider.avoid && <Badge tone="avoid">⚠ Expensive</Badge>}
            {/* A provider needing a key nobody has set is not broken — it is
                not switched on yet, and saying so is actionable. */}
            {!provider.is_configured && <Badge tone="warn">Needs API key</Badge>}
            {provider.needs_browser && <Badge tone="warn">Not yet live</Badge>}
            {provider.rate_reference_only && <Badge tone="info">Reference rate</Badge>}
          </div>
          {provider.notes && <p className="row-notes">{provider.notes}</p>}
        </div>
      </div>

      <div className="row-meta">
        <div className="meta-item">
          <span className="meta-label">Corridors</span>
          <span className="meta-val">
            {provider.corridors
              .map((c) => (c === "*->*" ? "Global" : c.replace("->", " → ").replace("*", "any")))
              .join(", ")}
          </span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Transfer size</span>
          <span className="meta-val">{limits || "No published limit"}</span>
        </div>
      </div>

      <div className="row-actions">
        <Link href={`/providers/${provider.slug}`} className="row-link">Details</Link>
        {url && (
          <a href={url} target="_blank" rel="noopener noreferrer" className="row-link">
            Visit ↗
          </a>
        )}
      </div>

      <style jsx>{`
        .row {
          display: grid;
          grid-template-columns: minmax(0, 2fr) minmax(0, 1.6fr) auto;
          gap: 1rem; align-items: start;
          padding: 1rem 1.25rem;
          background: var(--surface-float);
          border-radius: var(--radius-md);
        }
        .row-main { display: flex; gap: 0.75rem; align-items: flex-start; min-width: 0; }
        .row-icon { font-size: 1.1rem; line-height: 1.4; }
        .row-name { font-family: var(--font-display); font-weight: 700; font-size: 1rem; }
        .row-name :global(a) { color: var(--text); text-decoration: none; }
        .row-name :global(a:hover) { color: var(--secondary); }
        .row-badges { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.35rem; }
        .row-notes { font-size: 0.78rem; color: var(--muted); margin-top: 0.4rem; line-height: 1.5; }
        .row-meta { display: flex; flex-direction: column; gap: 0.5rem; min-width: 0; }
        .meta-item { display: flex; flex-direction: column; gap: 0.1rem; }
        .meta-label {
          font-size: 0.62rem; letter-spacing: 0.05em; text-transform: uppercase;
          color: var(--muted); font-weight: 600;
        }
        .meta-val { font-size: 0.8rem; color: var(--text-mid); }
        .row-actions { display: flex; flex-direction: column; gap: 0.35rem; align-items: flex-end; }
        .row-link {
          font-size: 0.78rem; font-weight: 600; color: var(--secondary);
          text-decoration: none; white-space: nowrap;
        }
        .row-link:hover { text-decoration: underline; }
        @media (max-width: 760px) {
          .row { grid-template-columns: 1fr; }
          .row-actions { flex-direction: row; align-items: center; }
        }
      `}</style>
    </li>
  );
}

const GROUPS = [
  { key: "au", title: "Sending from Australia", corridor: "AUD:INR" },
  { key: "in", title: "Sending from India", corridor: "INR:AUD" },
];

export default function ProviderDirectory() {
  const [data, setData] = useState(null);
  const [groups, setGroups] = useState({});
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      listProviders(),
      ...GROUPS.map((g) => listProviders({ corridor: g.corridor })),
    ])
      .then(([all, ...byCorridor]) => {
        if (cancelled) return;
        setData(all);
        setGroups(
          Object.fromEntries(
            GROUPS.map((g, i) => [g.key, byCorridor[i]?.providers || []])
          )
        );
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || "Could not load the provider list.");
      });

    return () => { cancelled = true; };
  }, []);

  if (error) {
    return (
      <p className="dir-error">
        {error}
        <style jsx>{`.dir-error { color: var(--error); font-size: 0.85rem; }`}</style>
      </p>
    );
  }

  if (!data) {
    return (
      <div className="dir-loading">
        {[1, 2, 3, 4].map((i) => <div key={i} className="skeleton-line" style={{ height: 56 }} />)}
        <style jsx>{`.dir-loading { display: flex; flex-direction: column; gap: 0.75rem; }`}</style>
      </div>
    );
  }

  return (
    <div className="dir">
      <p className="dir-summary">
        <strong>{data.total}</strong> providers compared on every search — fintechs,
        brokers, neobanks and the banks they beat.
        {data.hidden_benchmark > 0 && (
          <span className="dir-hidden">
            {" "}({data.hidden_benchmark} competitor{data.hidden_benchmark === 1 ? "" : "s"} tracked
            for benchmarking, never shown in results.)
          </span>
        )}
      </p>

      {GROUPS.map((group) => {
        const list = groups[group.key] || [];
        if (!list.length) return null;
        return (
          <section key={group.key} className="dir-group">
            <h3 className="dir-group-title">
              {group.title} <span className="dir-count">{list.length}</span>
            </h3>
            <ul className="dir-list">
              {list.map((p) => <ProviderRow key={p.slug} provider={p} />)}
            </ul>
          </section>
        );
      })}

      <style jsx>{`
        .dir { display: flex; flex-direction: column; gap: 2rem; }
        .dir-summary { font-size: 0.9rem; color: var(--text-mid); line-height: 1.6; }
        .dir-summary strong { color: var(--text); font-family: var(--font-display); }
        .dir-hidden { color: var(--muted); }
        .dir-group { display: flex; flex-direction: column; gap: 0.75rem; }
        .dir-group-title {
          font-family: var(--font-display); font-weight: 700; font-size: 1.05rem;
          display: flex; align-items: center; gap: 0.5rem;
        }
        .dir-count {
          font-size: 0.7rem; font-weight: 700; color: var(--secondary);
          background: var(--secondary-dim); border-radius: var(--radius-full);
          padding: 0.1rem 0.5rem;
        }
        .dir-list { list-style: none; display: flex; flex-direction: column; gap: 0.6rem; padding: 0; }
      `}</style>
    </div>
  );
}
