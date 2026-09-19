import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useAuth, useUser } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";
import Nav from "../components/Nav";
import { getMe, updateMe } from "../lib/api";
import { CURRENCIES } from "../lib/currencies";
import { signInPath } from "../lib/redirect";

const SECTIONS = [
  { key: "profile", icon: "👤", label: "Profile" },
  { key: "corridors", icon: "⇄", label: "Corridors" },
  { key: "notifications", icon: "🔔", label: "Notifications" },
  { key: "security", icon: "🔒", label: "Security" },
];

export default function Settings() {
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { user } = useUser();

  const [section, setSection] = useState("profile");
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const [fullName, setFullName] = useState("");
  const [whatsapp, setWhatsapp] = useState("");
  const [corrFrom, setCorrFrom] = useState("GBP");
  const [corrTo, setCorrTo] = useState("INR");
  const [homeCurrency, setHomeCurrency] = useState("GBP");

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { router.replace(signInPath(router.asPath)); return; }
    loadProfile();
  }, [isLoaded, isSignedIn]);

  const loadProfile = async () => {
    setLoading(true);
    try {
      const token = await getToken();
      const me = await getMe(token);
      setProfile(me);
      setFullName(me.full_name || "");
      setWhatsapp(me.whatsapp_number || "");
      setCorrFrom(me.corridor_from || "GBP");
      setCorrTo(me.corridor_to || "INR");
      setHomeCurrency(me.home_currency || "GBP");
    } catch (e) {
      if (e?.status === 401) { router.replace(signInPath(router.asPath)); return; }
      // No row yet means onboarding never finished — finish it, rather than
      // showing an empty settings page over a profile that doesn't exist.
      if (e?.status === 404) { router.replace("/onboarding?redirect_url=%2Fsettings"); return; }
      setError(e.message || "Failed to load profile.");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (data) => {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const token = await getToken();
      const updated = await updateMe(token, data);
      setProfile(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e.message || "Failed to save changes.");
    } finally {
      setSaving(false);
    }
  };

  const initials = user?.firstName
    ? `${user.firstName[0]}${user.lastName?.[0] || ""}`.toUpperCase()
    : "?";

  return (
    <>
      <Head>
        <title>Account Settings — Vaulto</title>
        <meta name="description" content="Manage your Vaulto account settings, corridors, and notification preferences." />
      </Head>
      <Nav variant="light" showDashboardLink />

      <div className="settings-layout container">
        {/* Sidebar */}
        <aside className="settings-sidebar">
          <p className="label-sm" style={{ padding: "1rem 0.75rem 0.5rem" }}>Settings</p>
          {SECTIONS.map(s => (
            <button
              key={s.key}
              className={`settings-link ${section === s.key ? "settings-link-active" : ""}`}
              onClick={() => setSection(s.key)}
              id={`settings-${s.key}`}
            >
              <span>{s.icon}</span> {s.label}
            </button>
          ))}
          <div style={{ padding: "1rem 0.75rem", borderTop: "1px solid var(--surface-high)", marginTop: "1rem" }}>
            <Link href="/dashboard" className="btn-ghost" style={{ width: "100%", justifyContent: "center", fontSize: "0.85rem" }}>
              ← Dashboard
            </Link>
          </div>
        </aside>

        {/* Main content */}
        <main className="settings-main">
          {error && <div className="error-box" style={{ marginBottom: "1.5rem" }}>⚠️ {error}</div>}
          {saved && <div style={{ background: "var(--tertiary-dim)", color: "var(--tertiary)", borderRadius: "var(--radius-md)", padding: "0.75rem 1rem", marginBottom: "1rem", fontSize: "0.875rem" }}>✓ Changes saved successfully</div>}

          {/* Profile */}
          {section === "profile" && (
            <div className="card">
              <h2 className="headline" style={{ marginBottom: "1.5rem" }}>Profile</h2>
              {loading ? <div className="loading-box"><div className="spinner" /></div> : (
                <>
                  <div className="settings-avatar">
                    <div className="big-avatar">{initials}</div>
                    <div>
                      <p style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "1.1rem" }}>{user?.fullName || fullName}</p>
                      <p style={{ color: "var(--muted)", fontSize: "0.875rem" }}>{user?.primaryEmailAddress?.emailAddress}</p>
                    </div>
                  </div>
                  <div className="settings-form">
                    <div className="field">
                      <label htmlFor="pf-name">Full name</label>
                      <input id="pf-name" type="text" value={fullName} onChange={e => setFullName(e.target.value)} />
                    </div>
                    <div className="field">
                      <label htmlFor="pf-email">Email (from Clerk)</label>
                      <input id="pf-email" type="email" value={user?.primaryEmailAddress?.emailAddress || ""} disabled style={{ opacity: 0.6 }} />
                    </div>
                    <div className="field">
                      <label htmlFor="pf-whatsapp">WhatsApp number</label>
                      <input id="pf-whatsapp" type="tel" value={whatsapp} onChange={e => setWhatsapp(e.target.value)} placeholder="+44 7700 000000" />
                    </div>
                    <button className="btn-secondary" onClick={() => handleSave({ full_name: fullName, whatsapp_number: whatsapp })} disabled={saving} id="save-profile">
                      {saving ? "Saving…" : "Save changes"}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}

          {/* Corridors */}
          {section === "corridors" && (
            <div className="card">
              <h2 className="headline" style={{ marginBottom: "1.5rem" }}>Corridors</h2>
              {loading ? <div className="loading-box"><div className="spinner" /></div> : (
                <div className="settings-form">
                  <p style={{ color: "var(--text-mid)", fontSize: "0.875rem", marginBottom: "1.5rem" }}>
                    Your saved corridor is used for quick comparisons on the dashboard.
                  </p>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                    <div className="field">
                      <label htmlFor="corr-from">Send from</label>
                      <select id="corr-from" value={corrFrom} onChange={e => setCorrFrom(e.target.value)}>
                        {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code} — {c.name}</option>)}
                      </select>
                    </div>
                    <div className="field">
                      <label htmlFor="corr-to">Recipient gets</label>
                      <select id="corr-to" value={corrTo} onChange={e => setCorrTo(e.target.value)}>
                        {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code} — {c.name}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="field" style={{ marginTop: "0.75rem" }}>
                    <label htmlFor="home-ccy">Home currency</label>
                    <select id="home-ccy" value={homeCurrency} onChange={e => setHomeCurrency(e.target.value)}>
                      {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code} — {c.name}</option>)}
                    </select>
                  </div>
                  {corrFrom === corrTo && (
                    <p className="text-xs" style={{ color: "var(--error)", marginTop: "0.5rem" }}>
                      Send and receive currencies must be different — there&rsquo;s nothing to compare otherwise.
                    </p>
                  )}
                  <button className="btn-secondary" style={{ marginTop: "0.5rem" }} onClick={() => handleSave({ corridor_from: corrFrom, corridor_to: corrTo, home_currency: homeCurrency })} disabled={saving || corrFrom === corrTo} id="save-corridors">
                    {saving ? "Saving…" : "Save corridor"}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Notifications */}
          {section === "notifications" && (
            <div className="card">
              <h2 className="headline" style={{ marginBottom: "1.5rem" }}>Notifications</h2>
              <div className="notif-row">
                <div>
                  <p style={{ fontWeight: 600 }}>Email alerts</p>
                  <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>Receive rate alert notifications via email</p>
                </div>
                <div className="notif-toggle notif-on">Always on</div>
              </div>
              <div className="notif-row">
                <div>
                  <p style={{ fontWeight: 600 }}>WhatsApp alerts</p>
                  <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                    {profile?.whatsapp_number ? `Connected: ${profile.whatsapp_number}` : "Requires phone number in Profile"}
                  </p>
                </div>
                <div className={`notif-toggle ${profile?.whatsapp_number ? "notif-on" : "notif-off"}`}>
                  {profile?.whatsapp_number ? "Active" : "Not set"}
                </div>
              </div>
              {!profile?.whatsapp_number && (
                <div style={{ marginTop: "1rem" }}>
                  <button className="btn-ghost" onClick={() => setSection("profile")} style={{ fontSize: "0.875rem" }}>
                    Add phone number in Profile →
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Security */}
          {section === "security" && (
            <div className="card">
              <h2 className="headline" style={{ marginBottom: "1.5rem" }}>Security</h2>
              <div className="security-item">
                <div>
                  <p style={{ fontWeight: 600 }}>Password</p>
                  <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>Managed by Clerk secure authentication</p>
                </div>
                <span className="pill pill-tertiary">✓ Secure</span>
              </div>
              <div className="security-item">
                <div>
                  <p style={{ fontWeight: 600 }}>Two-factor authentication</p>
                  <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>Add an extra layer of security to your account</p>
                </div>
                <span className="pill pill-muted">Via Clerk dashboard</span>
              </div>
              <div className="security-item">
                <div>
                  <p style={{ fontWeight: 600 }}>Data encryption</p>
                  <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>All data encrypted at rest and in transit</p>
                </div>
                <span className="pill pill-tertiary">✓ Active</span>
              </div>
            </div>
          )}
        </main>
      </div>

      <style jsx>{`
        .settings-layout { display: grid; grid-template-columns: 220px 1fr; gap: 2rem; padding: 3rem 1.5rem 6rem; min-height: 70vh; align-items: start; }
        @media (max-width: 768px) { .settings-layout { grid-template-columns: 1fr; } .settings-sidebar { display: flex; flex-direction: row; flex-wrap: wrap; gap: 0.5rem; } }

        .settings-sidebar { background: var(--surface-float); border-radius: var(--radius-lg); box-shadow: var(--shadow-sm); overflow: hidden; }
        .settings-link { display: flex; align-items: center; gap: 0.65rem; padding: 0.75rem 0.85rem; background: none; border: none; width: 100%; text-align: left; font-family: var(--font-body); font-size: 0.9rem; color: var(--text-mid); cursor: pointer; border-radius: var(--radius-md); margin: 0.1rem 0.5rem; width: calc(100% - 1rem); transition: background 0.15s, color 0.15s; }
        .settings-link:hover { background: var(--surface-low); color: var(--text); }
        .settings-link-active { background: var(--secondary-dim) !important; color: var(--secondary) !important; font-weight: 600; }

        .settings-avatar { display: flex; align-items: center; gap: 1.25rem; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--surface-high); }
        .big-avatar { width: 64px; height: 64px; border-radius: 50%; background: linear-gradient(135deg, var(--secondary), var(--tertiary)); display: flex; align-items: center; justify-content: center; font-family: var(--font-display); font-weight: 800; font-size: 1.4rem; color: white; flex-shrink: 0; }
        .settings-form { display: flex; flex-direction: column; gap: 1rem; }

        .notif-row { display: flex; align-items: center; justify-content: space-between; padding: 1rem 0; border-bottom: 1px solid var(--surface-high); gap: 1rem; }
        .notif-row:last-of-type { border-bottom: none; }
        .notif-toggle { font-size: 0.75rem; font-weight: 600; padding: 0.25rem 0.75rem; border-radius: var(--radius-full); }
        .notif-on { background: var(--tertiary-dim); color: var(--tertiary); }
        .notif-off { background: var(--surface-high); color: var(--muted); }

        .security-item { display: flex; align-items: center; justify-content: space-between; padding: 1rem 0; border-bottom: 1px solid var(--surface-high); gap: 1rem; }
        .security-item:last-child { border-bottom: none; }
      `}</style>
    </>
  );
}
