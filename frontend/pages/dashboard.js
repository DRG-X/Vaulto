import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useAuth, useUser, useClerk } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";
import CompareWidget from "../components/CompareWidget";
import AlertModal from "../components/AlertModal";
import { getMe, listComparisons, listAlerts, syncUser } from "../lib/api";
import { money, DASH } from "../lib/format";
import { isAdmin } from "../lib/admin";
import { signInPath } from "../lib/redirect";

// ── SVG Icons — outlined stroke style matching target design ────────────────
const Icons = {
  Dashboard: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
  Transfers: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 16V4m0 0L3 8m4-4l4 4" />
      <path d="M17 8v12m0 0l4-4m-4 4l-4-4" />
    </svg>
  ),
  History: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 3" />
    </svg>
  ),
  Alerts: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 01-3.46 0" />
    </svg>
  ),
  Analytics: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
      <polyline points="16 7 22 7 22 13" />
    </svg>
  ),
};

const NAV_ITEMS = [
  { key: "dashboard", href: "/dashboard",                            Icon: Icons.Dashboard, label: "Dashboard" },
  { key: "transfers", href: "/results?from=GBP&to=INR&amount=1000", Icon: Icons.Transfers, label: "Transfers" },
  { key: "history",   href: "/history",                             Icon: Icons.History,   label: "History"   },
  { key: "alerts",    href: "/alerts",                              Icon: Icons.Alerts,    label: "Alerts"    },
];

function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export default function Dashboard() {
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { user } = useUser();
  const { signOut } = useClerk();

  const [profile,        setProfile]        = useState(null);
  const [comparisons,    setComparisons]    = useState([]);
  const [alerts,         setAlerts]         = useState([]);
  const [loading,        setLoading]        = useState(true);
  const [error,          setError]          = useState("");
  const [sidebarOpen,    setSidebarOpen]    = useState(false);
  const [alertModalOpen, setAlertModalOpen] = useState(false);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { router.replace(signInPath(router.asPath)); return; }
    // Wait for the Clerk user object. Syncing with a blank id used to be
    // refused, which left the dashboard without the row it then 404s on.
    if (!user?.id) return;

    const load = async () => {
      try {
        const syncToken = await getToken();
        await syncUser(syncToken, {
          clerk_id:  user.id,
          email:     user.primaryEmailAddress?.emailAddress || "",
          full_name: user.fullName || user.username || "",
        });
      } catch (_) {}

      setLoading(true);
      try {
        const token = await getToken();
        const [meResult, compsResult, altsResult] = await Promise.allSettled([
          getMe(token),
          listComparisons(token, { page: 1, limit: 5 }),
          listAlerts(token),
        ]);

        const me    = meResult.status    === "fulfilled" ? meResult.value    : null;
        const comps = compsResult.status === "fulfilled" ? compsResult.value : [];
        const alts  = altsResult.status  === "fulfilled" ? altsResult.value  : [];

        if (!me) {
          const err = meResult.reason || {};
          if      (err.status === 404) router.replace("/onboarding");
          else if (err.status === 401) router.replace(signInPath(router.asPath));
          else setError("Could not load your profile. Refresh to try again.");
          setLoading(false);
          return;
        }
        if (!me.is_onboarded) { router.replace("/onboarding"); return; }

        setProfile(me);
        setComparisons(Array.isArray(comps) ? comps : []);
        setAlerts(Array.isArray(alts)  ? alts  : []);

        const compsErr = compsResult.status === "rejected" ? compsResult.reason : null;
        const altsErr  = altsResult.status  === "rejected" ? altsResult.reason  : null;
        if ((compsErr && compsErr.status !== 404) || (altsErr && altsErr.status !== 404)) {
          setError("Some data failed to load — showing partial results.");
        }
      } catch (e) {
        setError(e.message || "Failed to load dashboard data.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [isLoaded, isSignedIn, user?.id]);

  const handleSignOut = async () => { await signOut(); router.push("/"); };

  const initials = user?.firstName
    ? `${user.firstName[0]}${user.lastName?.[0] || ""}`.toUpperCase()
    : "?";

  const firstName        = user?.firstName || "there";
  const corridor         = profile?.corridor_from && profile?.corridor_to
    ? `${profile.corridor_from} → ${profile.corridor_to}` : null;
  const activeAlerts     = (alerts || []).filter(a => a.is_active !== false).slice(0, 4);
  const totalComparisons = comparisons?.length || 0;
  const totalAlerts      = (alerts  || []).length;

  if (!isLoaded || (isLoaded && !isSignedIn)) return null;

  const isActive = (item) => {
    if (item.key === "dashboard") return router.pathname === "/dashboard";
    if (item.key === "transfers") return router.pathname === "/results";
    if (item.key === "history")   return router.pathname === "/history";
    if (item.key === "alerts")    return router.pathname === "/alerts";
    return false;
  };

  return (
    <>
      <Head>
        <title>Dashboard — Vaulto</title>
        <meta name="description" content="Your Vaulto dashboard — compare rates, track alerts, and view transfer history." />
      </Head>

      <div className="db-layout">

        {/* ══════════════════════════════════════════
            SIDEBAR — white light theme
        ══════════════════════════════════════════ */}
        <aside className={`db-sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>

          {/* Brand */}
          <div className="sb-brand-row">
            <Link href="/" className="sb-brand">
              <span className="sb-brand-mark">V</span>
              <span className="sb-brand-name">Vaulto</span>
            </Link>
          </div>

          {/* User profile card */}
          <div className="sb-profile-card">
            <div className="sb-profile-avatar">{initials}</div>
            <div className="sb-profile-info">
              <div className="sb-profile-name">{user?.fullName || firstName}</div>
              <div className="sb-profile-tier">
                {isAdmin(user?.id) ? "Admin Tier" : "Elite Tier"}
              </div>
            </div>
          </div>

          {/* Navigation */}
          <nav className="sb-nav">
            <p className="sb-nav-label">Navigation</p>

            {NAV_ITEMS.map(item => (
              <Link
                key={item.key}
                href={item.href}
                className={`sb-link ${isActive(item) ? "sb-link-active" : ""}`}
                onClick={() => setSidebarOpen(false)}
              >
                <span className="sb-link-icon"><item.Icon /></span>
                <span className="sb-link-label">{item.label}</span>
              </Link>
            ))}

            {isAdmin(user?.id) && (
              <Link href="/admin/analytics" className="sb-link">
                <span className="sb-link-icon"><Icons.Analytics /></span>
                <span className="sb-link-label">Analytics</span>
              </Link>
            )}
          </nav>

          {/* Bottom — Send Money CTA + logout */}
          <div className="sb-footer">
            <Link
              href={`/results?from=${profile?.corridor_from || "GBP"}&to=${profile?.corridor_to || "INR"}&amount=1000`}
              className="sb-send-btn"
              id="sidebar-send-money"
            >
              Send Money
            </Link>
            <button className="sb-logout-btn" onClick={handleSignOut} id="dashboard-logout">
              Log out
            </button>
          </div>
        </aside>

        {/* Mobile overlay */}
        {sidebarOpen && <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />}

        {/* ══════════════════════════════════════════
            MAIN CONTENT
        ══════════════════════════════════════════ */}
        <main className="db-main">

          {/* Mobile top bar */}
          <div className="db-mobile-header">
            <button className="hamburger" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Menu">
              <span className="ham-line" /><span className="ham-line" /><span className="ham-line" />
            </button>
            <Link href="/" className="logo" style={{ fontSize: "1.1rem" }}>
              <span className="logo-mark" style={{ width: 22, height: 22, fontSize: "0.7rem" }}>V</span>
              <span>Vaulto</span>
            </Link>
          </div>

          <div className="db-content">

            {/* Error banner */}
            {error && (
              <div className="error-box" style={{ marginBottom: "1.5rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div>⚠️ {error}</div>
                <div>
                  <button onClick={() => window.location.reload()} style={{ marginLeft: "1rem", background: "none", border: "none", cursor: "pointer", color: "inherit", textDecoration: "underline", fontWeight: "bold" }}>Retry</button>
                  <button onClick={() => setError("")}             style={{ marginLeft: "1rem", background: "none", border: "none", cursor: "pointer", color: "inherit", textDecoration: "underline" }}>Dismiss</button>
                </div>
              </div>
            )}

            {/* Greeting */}
            <div className="db-header">
              <p className="label-sm">Overview</p>
              <h1 className="display-md" style={{ margin: "0.25rem 0 0.5rem" }}>
                {getGreeting()}, {firstName}.
              </h1>
              {corridor && (
                <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
                  Your active corridor: <strong style={{ color: "var(--text-mid)" }}>{corridor}</strong>
                </p>
              )}
            </div>

            {/* Smart insight card */}
            {corridor && (
              <div className="smart-card anim-fade-up">
                <div>
                  <p className="label-sm" style={{ color: "rgba(255,255,255,0.5)", marginBottom: "0.5rem" }}>
                    Smart Insight — {corridor}
                  </p>
                  <h2 style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "1.3rem", color: "white", marginBottom: "0.5rem" }}>
                    Your corridor is active
                  </h2>
                  <p style={{ color: "rgba(255,255,255,0.6)", fontSize: "0.875rem", maxWidth: "480px" }}>
                    Live rates are available. Compare now to find the best provider for your next transfer.
                  </p>
                </div>
                <Link
                  href={`/results?from=${profile.corridor_from}&to=${profile.corridor_to}&amount=1000`}
                  className="btn-secondary"
                  style={{ flexShrink: 0, alignSelf: "flex-start" }}
                  id="dashboard-compare-now"
                >
                  Compare now →
                </Link>
              </div>
            )}

            {/* Quick Compare Widget */}
            <div className="card anim-fade-up anim-delay-1" style={{ marginBottom: "1.5rem" }}>
              <p className="label-sm" style={{ marginBottom: "1rem" }}>Quick Compare</p>
              <CompareWidget
                defaultFrom={profile?.corridor_from || "AUD"}
                defaultTo={profile?.corridor_to     || "INR"}
                defaultAmount={1000}
              />
            </div>

            {/* 2-col grid */}
            <div className="db-grid anim-fade-up anim-delay-2">

              {/* Recent Transfers */}
              <div className="card">
                <div className="card-section-header">
                  <p className="label-sm">Recent Transfers</p>
                  <Link href="/history" style={{ fontSize: "0.8rem", color: "var(--secondary)", textDecoration: "none", fontWeight: 600 }}>View all →</Link>
                </div>
                {loading ? (
                  [1,2,3].map(i => <div key={i} className="skeleton-line" style={{ margin: "0.75rem 0" }} />)
                ) : comparisons.length > 0 ? (
                  <div className="recent-list">
                    {comparisons.slice(0, 5).map((c, i) => {
                      // Picked by receive amount rather than list position:
                      // a snapshot saved under "fastest" or "lowest fee" is
                      // not ordered by who paid the most.
                      let best = null;
                      try {
                        const rows = JSON.parse(c.results_json || "[]").filter((r) => r && !r.error);
                        best = rows.sort((a, b) => b.receive_amount - a.receive_amount)[0] || null;
                      } catch {}
                      return (
                        <div key={i} className="recent-item">
                          <div>
                            <div className="recent-corridor">{c.from_currency} → {c.to_currency}</div>
                            <div className="recent-meta">
                              {new Date(c.created_at).toLocaleDateString()} · {best?.provider || DASH}
                              {best?.total_cost != null && (
                                <> · cost {money(best.total_cost, c.from_currency)} {c.from_currency}</>
                              )}
                            </div>
                          </div>
                          <Link href={`/results?from=${c.from_currency}&to=${c.to_currency}&amount=${c.amount}`} className="recent-rerun">
                            Re-run →
                          </Link>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="empty-state-sm">
                    <div style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>🔍</div>
                    <p>No comparisons yet</p>
                    <Link href="/results?from=GBP&to=INR&amount=1000" className="btn-secondary"
                      style={{ marginTop: "0.75rem", fontSize: "0.85rem", padding: "0.5rem 1rem" }}>
                      Start comparing →
                    </Link>
                  </div>
                )}
              </div>

              {/* Rate Alerts */}
              <div className="card">
                <div className="card-section-header">
                  <p className="label-sm">Rate Alerts</p>
                  <Link href="/alerts" style={{ fontSize: "0.8rem", color: "var(--secondary)", textDecoration: "none", fontWeight: 600 }}>Manage →</Link>
                </div>
                {loading ? (
                  [1,2].map(i => <div key={i} className="skeleton-line" style={{ margin: "0.75rem 0" }} />)
                ) : activeAlerts.length > 0 ? (
                  <div className="alerts-list">
                    {activeAlerts.map(a => (
                      <div key={a.id} className="alert-item">
                        <div>
                          <div className="alert-corridor">{a.from_currency} → {a.to_currency}</div>
                          <div className="alert-meta">Target: {a.target_rate} · {a.amount} {a.from_currency}</div>
                        </div>
                        <span className="pill pill-tertiary" style={{ fontSize: "0.65rem" }}>● Active</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state-sm">
                    <div style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>🔔</div>
                    <p>No active alerts</p>
                  </div>
                )}
                <button
                  className="btn-secondary"
                  style={{ width: "100%", justifyContent: "center", marginTop: "1rem", fontSize: "0.875rem" }}
                  onClick={() => setAlertModalOpen(true)}
                  id="dashboard-new-alert"
                >
                  + New Alert
                </button>
              </div>
            </div>

            {/* Stats row */}
            <div className="db-stats anim-fade-up anim-delay-3">
              <div className="stat-mini">
                <div className="stat-mini-value">{loading ? "—" : totalComparisons}</div>
                <div className="label-sm">Saved comparisons</div>
              </div>
              <div className="stat-mini">
                <div className="stat-mini-value">{loading ? "—" : totalAlerts}</div>
                <div className="label-sm">Active alerts</div>
              </div>
              <div className="stat-mini">
                <div className="stat-mini-value" style={{ fontSize: "1.1rem" }}>
                  {loading ? "—" : (corridor || "—")}
                </div>
                <div className="label-sm">Your corridor</div>
              </div>
            </div>
          </div>
        </main>
      </div>

      <AlertModal
        isOpen={alertModalOpen}
        onClose={() => setAlertModalOpen(false)}
        onSuccess={(newAlert) => { setAlerts(prev => [newAlert, ...prev]); setAlertModalOpen(false); }}
        defaultFrom={profile?.corridor_from || "GBP"}
        defaultTo={profile?.corridor_to     || "INR"}
        defaultAmount={1000}
        userWhatsapp={profile?.whatsapp_number}
      />

      <style jsx>{`
        /* ── Layout ── */
        .db-layout {
          display: flex;
          min-height: 100vh;
          background: var(--bg);
        }

        /* ══════════════════════════════════════════
           SIDEBAR — white light theme
        ══════════════════════════════════════════ */
        .db-sidebar {
          width: 240px;
          min-height: 100vh;
          background: #ffffff;
          border-right: 1px solid #f0f1f3;
          box-shadow: 2px 0 16px rgba(0, 0, 0, 0.04);
          display: flex;
          flex-direction: column;
          position: sticky;
          top: 0;
          height: 100vh;
          overflow-y: auto;
          flex-shrink: 0;
          z-index: 50;
        }
        @media (max-width: 900px) {
          .db-sidebar {
            position: fixed;
            left: -260px;
            transition: left 0.3s ease;
          }
          .sidebar-open {
            left: 0 !important;
            box-shadow: 4px 0 24px rgba(0,0,0,0.12);
          }
        }
        .sidebar-overlay {
          position: fixed; inset: 0; z-index: 40;
          background: rgba(0,0,0,0.35);
        }

        /* ── Brand row ── */
        .sb-brand-row {
          padding: 1.5rem 1.25rem 1.25rem;
          border-bottom: 1px solid #f3f4f6;
        }
        .sb-brand {
          display: flex; align-items: center; gap: 0.5rem;
          text-decoration: none;
        }
        .sb-brand-mark {
          width: 30px; height: 30px;
          background: linear-gradient(135deg, #0B1220, #0058BE);
          border-radius: 8px;
          display: flex; align-items: center; justify-content: center;
          font-family: var(--font-display);
          font-size: 0.85rem; font-weight: 900;
          color: white; flex-shrink: 0;
          box-shadow: 0 2px 8px rgba(0,88,190,0.2);
        }
        .sb-brand-name {
          font-family: var(--font-display);
          font-size: 1.2rem; font-weight: 800;
          letter-spacing: -0.03em; color: #0B1220;
        }

        /* ── User profile card ── */
        .sb-profile-card {
          margin: 1rem 0.875rem 0.25rem;
          background: #f8f9fb;
          border-radius: 12px;
          padding: 0.85rem 1rem;
          display: flex; align-items: center; gap: 0.75rem;
          border: 1px solid #f0f1f3;
        }
        .sb-profile-avatar {
          width: 38px; height: 38px; border-radius: 50%;
          background: linear-gradient(135deg, #0058BE, #10B981);
          display: flex; align-items: center; justify-content: center;
          font-family: var(--font-display);
          font-weight: 800; font-size: 0.85rem;
          color: white; flex-shrink: 0;
          box-shadow: 0 2px 8px rgba(0,88,190,0.25);
        }
        .sb-profile-info { min-width: 0; }
        .sb-profile-name {
          font-size: 0.82rem; font-weight: 700; color: #111827;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .sb-profile-tier {
          font-size: 0.62rem; font-weight: 700;
          letter-spacing: 0.07em; text-transform: uppercase;
          color: #0058BE; margin-top: 0.15rem;
        }

        /* ── Nav ── */
        .sb-nav {
          flex: 1;
          padding: 1rem 0.875rem 0.5rem;
          display: flex; flex-direction: column; gap: 0.15rem;
        }
        .sb-nav-label {
          font-size: 0.6rem; font-weight: 700;
          letter-spacing: 0.12em; text-transform: uppercase;
          color: #9ca3af;
          padding: 0 0.35rem; margin-bottom: 0.4rem;
        }

        /* Nav link */
        .sb-link {
          display: flex; align-items: center; gap: 0.7rem;
          padding: 0.65rem 0.85rem;
          border-radius: 10px;
          font-size: 0.875rem; font-weight: 500;
          color: #6b7280 !important;
          text-decoration: none;
          transition: background 0.15s, color 0.15s;
          border-left: 3px solid transparent;
        }
        .sb-link:hover {
          background: #f3f4f6;
          color: #111827 !important;
        }
        .sb-link-active {
          background: #eff6ff !important;
          color: #0058BE !important;
          font-weight: 600;
          border-left-color: #0058BE;
        }
        .sb-link-icon {
          display: flex; align-items: center; justify-content: center;
          width: 20px; flex-shrink: 0; opacity: 0.8;
        }
        .sb-link-active .sb-link-icon { opacity: 1; }
        .sb-link-label { line-height: 1; }

        /* ── Footer ── */
        .sb-footer {
          padding: 0.75rem 0.875rem 1.5rem;
          display: flex; flex-direction: column; gap: 0.5rem;
        }
        .sb-send-btn {
          display: flex; align-items: center; justify-content: center;
          background: #0B1220;
          color: #ffffff !important;
          font-family: var(--font-display);
          font-weight: 700; font-size: 0.9rem;
          padding: 0.85rem 1rem;
          border-radius: 12px; text-decoration: none;
          transition: opacity 0.15s, transform 0.1s;
          box-shadow: 0 2px 10px rgba(11,18,32,0.18);
        }
        .sb-send-btn:hover { opacity: 0.88; transform: translateY(-1px); }

        .sb-logout-btn {
          background: none; border: none;
          color: #9ca3af;
          font-family: var(--font-body);
          font-size: 0.8rem; font-weight: 500;
          cursor: pointer; padding: 0.4rem;
          text-align: center;
          transition: color 0.15s;
        }
        .sb-logout-btn:hover { color: #6b7280; }

        /* ══════════════════════════════════════════
           MAIN CONTENT
        ══════════════════════════════════════════ */
        .db-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }

        .db-mobile-header {
          display: none;
          align-items: center; gap: 1rem;
          padding: 1rem 1.5rem;
          background: var(--surface-float);
          border-bottom: 1px solid var(--surface-high);
          position: sticky; top: 0; z-index: 30;
        }
        @media (max-width: 900px) { .db-mobile-header { display: flex; } }

        .hamburger {
          display: flex; flex-direction: column; gap: 5px;
          background: none; border: none; cursor: pointer; padding: 4px;
        }
        .ham-line { display: block; width: 22px; height: 2px; background: var(--text); border-radius: 2px; }

        .db-content { padding: 2rem 2.5rem; max-width: 1000px; }
        @media (max-width: 900px) { .db-content { padding: 1.5rem; } }

        .db-header { margin-bottom: 2rem; }

        .smart-card {
          background: linear-gradient(135deg, var(--primary) 0%, #1e3460 100%);
          border-radius: var(--radius-xl); padding: 2rem;
          display: flex; align-items: flex-start;
          justify-content: space-between;
          gap: 1.5rem; margin-bottom: 1.5rem;
          position: relative; overflow: hidden;
        }
        .smart-card::before {
          content: "";
          position: absolute; top: -40px; right: -40px;
          width: 180px; height: 180px;
          background: radial-gradient(circle, rgba(0,88,190,0.2), transparent 70%);
          border-radius: 50%;
        }
        @media (max-width: 600px) { .smart-card { flex-direction: column; } }

        .db-grid {
          display: grid; grid-template-columns: 1fr 1fr;
          gap: 1.25rem; margin-bottom: 1.5rem;
        }
        @media (max-width: 700px) { .db-grid { grid-template-columns: 1fr; } }

        .card-section-header {
          display: flex; align-items: center;
          justify-content: space-between; margin-bottom: 1rem;
        }

        .recent-list { display: flex; flex-direction: column; }
        .recent-item {
          display: flex; align-items: center;
          justify-content: space-between;
          padding: 0.75rem 0;
          border-bottom: 1px solid var(--surface-high);
        }
        .recent-item:last-child { border-bottom: none; }
        .recent-corridor {
          font-family: var(--font-display);
          font-weight: 700; font-size: 0.95rem; color: var(--text);
        }
        .recent-meta { font-size: 0.75rem; color: var(--muted); margin-top: 0.15rem; }
        .recent-rerun { font-size: 0.8rem; color: var(--secondary); text-decoration: none; font-weight: 600; }
        .recent-rerun:hover { text-decoration: underline; }

        .alerts-list { display: flex; flex-direction: column; }
        .alert-item {
          display: flex; align-items: center;
          justify-content: space-between;
          padding: 0.75rem 0;
          border-bottom: 1px solid var(--surface-high);
        }
        .alert-item:last-child { border-bottom: none; }
        .alert-corridor { font-family: var(--font-display); font-weight: 700; font-size: 0.95rem; }
        .alert-meta { font-size: 0.75rem; color: var(--muted); margin-top: 0.15rem; }

        .empty-state-sm { text-align: center; padding: 1.5rem 0; color: var(--muted); font-size: 0.875rem; }
        .empty-state-sm p { margin-bottom: 0.25rem; }

        .db-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
        @media (max-width: 600px) { .db-stats { grid-template-columns: 1fr; } }
        .stat-mini {
          background: var(--surface-float);
          border-radius: var(--radius-md);
          padding: 1.25rem; box-shadow: var(--shadow-sm); text-align: center;
        }
        .stat-mini-value {
          font-family: var(--font-display);
          font-size: 1.8rem; font-weight: 800;
          letter-spacing: -0.03em; color: var(--text); margin-bottom: 0.25rem;
        }
      `}</style>
    </>
  );
}