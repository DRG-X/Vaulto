import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useAuth } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";
import Nav from "../components/Nav";
import Footer from "../components/Footer";
import { listComparisons } from "../lib/api";
import { money, rate, DASH } from "../lib/format";

const fmt = (n, dec = 2) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(n);

/**
 * Summarise a saved comparison.
 *
 * Comparisons saved before the engine reported true cost have no `total_cost`,
 * so it is returned as null and rendered as "—". Back-filling it here would
 * mean recomputing a markup against a mid-market rate we never stored — a
 * number that looks precise and is not.
 */
function parseResults(json) {
  try {
    const rows = JSON.parse(json || "[]").filter((r) => r && !r.error);
    if (!rows.length) return { best: null, worst: null, spread: null };

    const sorted = [...rows].sort((a, b) => b.receive_amount - a.receive_amount);
    const best = sorted[0];
    const worst = sorted[sorted.length - 1];

    return {
      best,
      worst,
      spread: sorted.length > 1 ? best.receive_amount - worst.receive_amount : null,
    };
  } catch {
    return { best: null, worst: null, spread: null };
  }
}

export default function History() {
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken } = useAuth();

  const [comparisons, setComparisons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { router.replace("/auth"); return; }
    loadComparisons(page);
  }, [isLoaded, isSignedIn, page]);

  const loadComparisons = async (p) => {
    setLoading(true);
    setError("");
    try {
      const token = await getToken();
      const data = await listComparisons(token, { page: p, limit: 20 });
      const items = Array.isArray(data) ? data : [];
      setComparisons(items);
      setHasMore(items.length === 20);
    } catch (e) {
      setError(e.message || "Failed to load history.");
    } finally {
      setLoading(false);
    }
  };

  const filtered = comparisons.filter(c => {
    if (!filter) return true;
    const q = filter.toUpperCase();
    return c.from_currency?.includes(q) || c.to_currency?.includes(q);
  });

  const exportCSV = () => {
    const headers = [
      "Date", "From", "To", "Amount",
      "Best Rate", "True Cost", "Best Provider", "Recipient Gets",
    ];
    const rows = filtered.map(c => {
      const { best } = parseResults(c.results_json);
      return [
        new Date(c.created_at).toLocaleDateString(),
        c.from_currency, c.to_currency,
        c.amount,
        best?.exchange_rate ?? "",
        best?.total_cost ?? "",
        best?.provider ?? "",
        best?.receive_amount ?? "",
      ];
    });
    // Quote every cell: provider names contain spaces and, once rails are
    // included, commas — an unquoted CSV would silently shift columns.
    const escape = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [headers, ...rows].map(r => r.map(escape).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "vaulto-history.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <Head>
        <title>Transfer History — Vaulto</title>
        <meta name="description" content="View your Vaulto comparison history and re-run past searches." />
      </Head>
      <Nav variant="light" showDashboardLink />

      <div className="history-page">
        <div className="container">
          <div className="history-header">
            <div>
              <p className="label-sm" style={{ marginBottom: "0.4rem" }}>
                <Link href="/dashboard" style={{ color: "var(--secondary)", textDecoration: "none" }}>← Dashboard</Link>
              </p>
              <h1 className="display-md">Transfer History</h1>
            </div>
            <div className="history-actions">
              <input
                type="text"
                placeholder="Filter by currency…"
                value={filter}
                onChange={e => setFilter(e.target.value)}
                className="history-filter"
                id="history-filter"
              />
              <button
                className="btn-ghost"
                onClick={exportCSV}
                disabled={filtered.length === 0}
                id="export-csv"
              >
                ↓ Export CSV
              </button>
            </div>
          </div>

          {error && <div className="error-box">⚠️ {error}</div>}

          {loading ? (
            <div className="loading-box"><div className="spinner" /><p>Loading history…</p></div>
          ) : filtered.length === 0 ? (
            <div className="history-empty card">
              <div style={{ fontSize: "2.5rem", marginBottom: "1rem" }}>📊</div>
              <h2>No comparisons yet</h2>
              <p style={{ color: "var(--muted)", margin: "0.5rem 0 1.5rem" }}>Your saved comparisons will appear here.</p>
              <Link href="/results?from=GBP&to=INR&amount=1000" className="btn-secondary" id="history-try-compare">
                Try a comparison →
              </Link>
            </div>
          ) : (
            <>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Corridor</th>
                      <th>Amount</th>
                      <th>Best Rate</th>
                      <th>True Cost</th>
                      <th>Best Provider</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((c, i) => {
                      const { best, spread } = parseResults(c.results_json);
                      return (
                        <tr key={i}>
                          <td style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                            {new Date(c.created_at).toLocaleDateString()}
                          </td>
                          <td>
                            <span style={{ fontFamily: "var(--font-display)", fontWeight: 700 }}>
                              {c.from_currency} → {c.to_currency}
                            </span>
                          </td>
                          <td>{money(c.amount, c.from_currency)} {c.from_currency}</td>
                          <td style={{ color: "var(--tertiary)", fontWeight: 700 }}>
                            {best ? rate(best.exchange_rate) : DASH}
                          </td>
                          <td>
                            {/* True cost, where the saved snapshot has it.
                                Older saves predate the field. */}
                            {best?.total_cost != null
                              ? `${money(best.total_cost, c.from_currency)} ${c.from_currency}`
                              : DASH}
                          </td>
                          <td style={{ fontWeight: 600 }}>
                            {best?.provider || DASH}
                            {spread > 0 && (
                              <div style={{ fontSize: "0.72rem", color: "var(--muted)", fontWeight: 400 }}>
                                {money(spread, c.to_currency)} {c.to_currency} ahead of worst
                              </div>
                            )}
                          </td>
                          <td>
                            <Link
                              href={`/results?from=${c.from_currency}&to=${c.to_currency}&amount=${c.amount}`}
                              style={{ color: "var(--secondary)", fontSize: "0.85rem", fontWeight: 600, textDecoration: "none" }}
                            >
                              Re-run →
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="pagination">
                <button
                  className="btn-ghost"
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  id="prev-page"
                >
                  ← Previous
                </button>
                <span className="page-indicator">Page {page}</span>
                <button
                  className="btn-ghost"
                  onClick={() => setPage(p => p + 1)}
                  disabled={!hasMore}
                  id="next-page"
                >
                  Next →
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <Footer />

      <style jsx>{`
        .history-page { padding: 3rem 0 6rem; min-height: 70vh; }
        .history-header {
          display: flex; align-items: flex-start; justify-content: space-between;
          gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap;
        }
        .history-actions { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
        .history-filter {
          padding: 0.65rem 1rem;
          background: var(--surface-float);
          border: 1px solid var(--surface-high);
          border-radius: var(--radius-md);
          font-family: var(--font-body);
          font-size: 0.875rem;
          color: var(--text);
          outline: none;
          transition: border-color 0.15s;
          width: 200px;
        }
        .history-filter:focus { border-color: var(--secondary); }
        .history-empty { text-align: center; padding: 4rem 2rem; }
        .history-empty h2 { font-family: var(--font-display); font-weight: 700; font-size: 1.3rem; }
        .pagination { display: flex; align-items: center; gap: 1rem; justify-content: center; margin-top: 2rem; }
        .page-indicator { font-size: 0.875rem; color: var(--muted); }
      `}</style>
    </>
  );
}
