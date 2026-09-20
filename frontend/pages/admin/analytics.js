import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useAuth, useUser } from "../../contexts/AuthContext";
import Head from "next/head";
import Link from "next/link";
import { listComparisons } from "../../lib/api";
import { isAdmin } from "../../lib/admin";

const SIDEBAR_LINKS = [
  { href: "/admin/analytics", label: "📊 Analytics" },
  { href: "/dashboard", label: "⊞ User Dashboard" },
  { href: "/", label: "🌐 Site Home" },
];

const fmt = (n, dec = 2) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(n);

const MOCK_STATS = [
  { label: "Total Users", value: "50,241", trend: "+18%", icon: "👥" },
  { label: "Comparisons Today", value: "1,842", trend: "+7%", icon: "⇄" },
  { label: "Avg Savings", value: "₹4,820", trend: "+2%", icon: "💰" },
  { label: "Provider Split", value: "Wise 48%", icon: "📊" },
];

const MOCK_CORRIDORS = [
  { corridor: "GBP → INR", count: 12400, pct: 100 },
  { corridor: "AUD → INR", count: 9200, pct: 74 },
  { corridor: "USD → INR", count: 7800, pct: 63 },
  { corridor: "EUR → INR", count: 5100, pct: 41 },
  { corridor: "CAD → INR", count: 3200, pct: 26 },
];

export default function AdminAnalytics() {
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken, signOut } = useAuth();
  const { user } = useUser();

  const [comparisons, setComparisons] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { router.replace("/auth"); return; }
    if (!isAdmin(user?.id)) {
      router.replace("/dashboard");
      return;
    }
    getToken().then(token => listComparisons(token, { page: 1, limit: 10 }))
      .then(data => setComparisons(Array.isArray(data) ? data : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isLoaded, isSignedIn, user?.id]);

  const handleSignOut = async () => { await signOut(); router.push("/"); };

  return (
    <>
      <Head>
        <title>Admin Analytics — Vaulto</title>
      </Head>
      <div className="admin-layout">
        {/* Sidebar */}
        <aside className="admin-sidebar">
          <div className="admin-logo-wrap">
            <Link href="/" className="logo" style={{ color: "white", fontSize: "1.1rem" }}>
              <span className="logo-mark" style={{ width: 22, height: 22, fontSize: "0.7rem" }}>V</span>
              <span>Vaulto</span>
            </Link>
            <span style={{ fontSize: "0.6rem", background: "#7c3aed", color: "white", padding: "0.1rem 0.45rem", borderRadius: "999px", fontWeight: 700, letterSpacing: "0.06em" }}>ADMIN</span>
          </div>
          <nav className="admin-nav">
            {SIDEBAR_LINKS.map(l => (
              <Link key={l.href} href={l.href} className={`sidebar-link ${router.pathname === l.href ? "sidebar-link-active" : ""}`}>{l.label}</Link>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="sidebar-user">
              <div className="sb-avatar">{user?.firstName?.[0] || "A"}</div>
              <div>
                <div className="sb-name">{user?.fullName || "Admin"}</div>
                <div className="sb-verified" style={{ color: "#7c3aed", fontSize: "0.65rem" }}>Admin</div>
              </div>
            </div>
            <button className="btn-ghost-sm sidebar-logout" onClick={handleSignOut}>Logout</button>
          </div>
        </aside>

        <main className="admin-main">
          <div className="admin-content">
            <div style={{ marginBottom: "2rem" }}>
              <p className="label-sm" style={{ marginBottom: "0.25rem" }}>Internal dashboard</p>
              <h1 style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "2rem", letterSpacing: "-0.03em" }}>Analytics</h1>
            </div>

            {/* Stats row */}
            <div className="admin-stats-grid">
              {MOCK_STATS.map(s => (
                <div key={s.label} className="card-sm admin-stat">
                  <div className="admin-stat-header">
                    <span>{s.icon}</span>
                    <span className="label-sm">{s.label}</span>
                  </div>
                  <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "1.6rem", letterSpacing: "-0.03em", marginTop: "0.25rem" }}>{s.value}</div>
                  {s.trend && <span style={{ fontSize: "0.75rem", color: "var(--tertiary)", fontWeight: 600 }}>↑ {s.trend}</span>}
                </div>
              ))}
            </div>

            {/* Charts row */}
            <div className="admin-charts-grid">
              {/* Top Corridors */}
              <div className="card">
                <p className="label-sm" style={{ marginBottom: "1.25rem" }}>Top corridors</p>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
                  {MOCK_CORRIDORS.map(c => (
                    <div key={c.corridor}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", marginBottom: "0.3rem" }}>
                        <span style={{ fontWeight: 600 }}>{c.corridor}</span>
                        <span style={{ color: "var(--muted)" }}>{fmt(c.count)}</span>
                      </div>
                      <div style={{ height: 6, background: "var(--surface-high)", borderRadius: 99 }}>
                        <div style={{ height: "100%", width: `${c.pct}%`, background: "var(--secondary)", borderRadius: 99, transition: "width 1s ease" }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Provider win rate */}
              <div className="card">
                <p className="label-sm" style={{ marginBottom: "1.25rem" }}>Provider win rate</p>
                <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                  {[{ p: "Wise", pct: 48, color: "#0ea5e9" }, { p: "Remitly", pct: 31, color: "#f97316" }, { p: "Western Union", pct: 21, color: "#f59e0b" }].map(r => (
                    <div key={r.p}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", marginBottom: "0.3rem" }}>
                        <span style={{ fontWeight: 600 }}>{r.p}</span>
                        <span style={{ color: r.color, fontWeight: 700 }}>{r.pct}%</span>
                      </div>
                      <div style={{ height: 8, background: "var(--surface-high)", borderRadius: 99 }}>
                        <div style={{ height: "100%", width: `${r.pct}%`, background: r.color, borderRadius: 99 }} />
                      </div>
                    </div>
                  ))}
                </div>
                <p style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "1rem" }}>
                  Based on best receive amount across all comparisons.
                </p>
              </div>
            </div>

            {/* Recent comparisons table */}
            <div className="card" style={{ marginTop: "1.5rem" }}>
              <p className="label-sm" style={{ marginBottom: "1rem" }}>Recent comparisons</p>
              {loading ? (
                <div className="loading-box"><div className="spinner" /></div>
              ) : comparisons.length > 0 ? (
                <div className="table-wrapper">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Corridor</th>
                        <th>Amount</th>
                        <th>Re-run</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparisons.map((c, i) => (
                        <tr key={i}>
                          <td style={{ color: "var(--muted)", fontSize: "0.85rem" }}>{new Date(c.created_at).toLocaleDateString()}</td>
                          <td style={{ fontFamily: "var(--font-display)", fontWeight: 700 }}>{c.from_currency} → {c.to_currency}</td>
                          <td>{fmt(c.amount)} {c.from_currency}</td>
                          <td>
                            <Link href={`/results?from=${c.from_currency}&to=${c.to_currency}&amount=${c.amount}`} style={{ color: "var(--secondary)", fontSize: "0.85rem", fontWeight: 600, textDecoration: "none" }}>View →</Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p style={{ color: "var(--muted)", textAlign: "center", padding: "2rem 0" }}>No comparison data yet.</p>
              )}
            </div>
          </div>
        </main>
      </div>

      <style jsx>{`
        .admin-layout { display: flex; min-height: 100vh; background: var(--bg); }
        .admin-sidebar { width: 220px; background: var(--primary); display: flex; flex-direction: column; position: sticky; top: 0; height: 100vh; overflow-y: auto; flex-shrink: 0; }
        .admin-logo-wrap { padding: 1.25rem 1rem; border-bottom: 1px solid rgba(255,255,255,0.06); display: flex; align-items: center; gap: 0.6rem; }
        .admin-nav { flex: 1; padding: 1rem 0.6rem; display: flex; flex-direction: column; gap: 0.2rem; }
        .sidebar-link { display: flex; align-items: center; padding: 0.65rem 0.75rem; border-radius: var(--radius-md); font-size: 0.875rem; font-weight: 500; color: rgba(255,255,255,0.6); text-decoration: none; transition: background 0.15s, color 0.15s; }
        .sidebar-link:hover { background: rgba(255,255,255,0.06); color: white; }
        .sidebar-link-active { background: rgba(255,255,255,0.1) !important; color: white !important; }
        .sidebar-bottom { padding: 0.75rem; border-top: 1px solid rgba(255,255,255,0.06); display: flex; flex-direction: column; gap: 0.6rem; }
        .sidebar-user { display: flex; align-items: center; gap: 0.6rem; }
        .sb-avatar { width: 32px; height: 32px; border-radius: 50%; background: #7c3aed; display: flex; align-items: center; justify-content: center; font-family: var(--font-display); font-weight: 800; font-size: 0.75rem; color: white; flex-shrink: 0; }
        .sb-name { font-size: 0.8rem; font-weight: 600; color: rgba(255,255,255,0.9); }
        .sidebar-logout { color: rgba(255,255,255,0.4); border-color: rgba(255,255,255,0.08); width: 100%; text-align: center; }
        .sidebar-logout:hover { color: rgba(255,255,255,0.8); }

        .admin-main { flex: 1; min-width: 0; }
        .admin-content { padding: 2.5rem; max-width: 1100px; }
        .admin-stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
        @media (max-width: 900px) { .admin-stats-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 500px) { .admin-stats-grid { grid-template-columns: 1fr; } }
        .admin-stat { display: flex; flex-direction: column; }
        .admin-stat-header { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.4rem; }
        .admin-charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }
        @media (max-width: 700px) { .admin-charts-grid { grid-template-columns: 1fr; } }
      `}</style>
    </>
  );
}
