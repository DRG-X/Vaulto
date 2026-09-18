import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useAuth } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";
import Nav from "../components/Nav";
import Footer from "../components/Footer";
import { railLabel } from "../lib/format";
import AlertModal from "../components/AlertModal";
import { listAlerts, updateAlert, deleteAlert, getMe } from "../lib/api";

export default function Alerts() {
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken } = useAuth();

  const [alerts, setAlerts] = useState([]);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editAlert, setEditAlert] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { router.replace("/auth"); return; }
    loadData();
  }, [isLoaded, isSignedIn]);

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const token = await getToken();
      const [alts, me] = await Promise.all([listAlerts(token), getMe(token)]);
      setAlerts(Array.isArray(alts) ? alts : []);
      setProfile(me);
    } catch (e) {
      setError(e.message || "Failed to load alerts.");
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (alert) => {
    const optimistic = alerts.map(a => a.id === alert.id ? { ...a, is_active: !a.is_active } : a);
    setAlerts(optimistic);
    try {
      const token = await getToken();
      await updateAlert(token, alert.id, { is_active: !alert.is_active });
    } catch {
      setAlerts(alerts); // rollback
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this alert?")) return;
    const prev = alerts;
    setAlerts(alerts.filter(a => a.id !== id));
    setDeletingId(id);
    try {
      const token = await getToken();
      await deleteAlert(token, id);
    } catch {
      setAlerts(prev);
    } finally {
      setDeletingId(null);
    }
  };

  const activeAlerts = alerts.filter(a => a.is_active !== false);
  const pausedAlerts = alerts.filter(a => a.is_active === false);

  return (
    <>
      <Head>
        <title>Rate Alerts — Vaulto</title>
        <meta name="description" content="Manage your Vaulto rate alerts. Get notified when your target exchange rate is reached." />
      </Head>
      <Nav variant="light" showDashboardLink />

      <div className="alerts-page">
        <div className="container">
          <div className="alerts-header">
            <div>
              <p className="label-sm" style={{ marginBottom: "0.4rem" }}>
                <Link href="/dashboard" style={{ color: "var(--secondary)", textDecoration: "none" }}>← Dashboard</Link>
              </p>
              <h1 className="display-md">Rate Alerts</h1>
              <p style={{ color: "var(--muted)", marginTop: "0.5rem" }}>
                Get notified when exchange rates hit your target.
              </p>
            </div>
            <button
              className="btn-secondary"
              onClick={() => { setEditAlert(null); setModalOpen(true); }}
              id="new-alert-btn"
            >
              + New Alert
            </button>
          </div>

          {error && (
            <div className="error-box">⚠️ {error}
              <button onClick={loadData} style={{ marginLeft: "1rem", background: "none", border: "none", cursor: "pointer", color: "inherit", textDecoration: "underline" }}>Retry</button>
            </div>
          )}

          {loading ? (
            <div className="loading-box"><div className="spinner" /><p>Loading alerts…</p></div>
          ) : alerts.length === 0 ? (
            <div className="alerts-empty card">
              <div className="empty-icon">🔔</div>
              <h2>No rate alerts yet</h2>
              <p>Set a target rate and we'll notify you when it's reached.</p>
              <button className="btn-secondary" onClick={() => setModalOpen(true)} style={{ marginTop: "1rem" }} id="create-first-alert">
                Create your first alert →
              </button>
            </div>
          ) : (
            <>
              {/* Active */}
              {activeAlerts.length > 0 && (
                <div className="alerts-section">
                  <div className="section-title">
                    <p className="label-sm">Active</p>
                    <span className="count-pill">{activeAlerts.length}</span>
                  </div>
                  <div className="alerts-grid">
                    {activeAlerts.map(a => <AlertCard key={a.id} alert={a} onToggle={handleToggle} onEdit={(a) => { setEditAlert(a); setModalOpen(true); }} onDelete={handleDelete} deleting={deletingId === a.id} />)}
                  </div>
                </div>
              )}
              {/* Paused */}
              {pausedAlerts.length > 0 && (
                <div className="alerts-section">
                  <div className="section-title">
                    <p className="label-sm">Paused</p>
                    <span className="count-pill count-muted">{pausedAlerts.length}</span>
                  </div>
                  <div className="alerts-grid">
                    {pausedAlerts.map(a => <AlertCard key={a.id} alert={a} onToggle={handleToggle} onEdit={(a) => { setEditAlert(a); setModalOpen(true); }} onDelete={handleDelete} deleting={deletingId === a.id} />)}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <AlertModal
        isOpen={modalOpen}
        onClose={() => { setModalOpen(false); setEditAlert(null); }}
        onSuccess={(result) => {
          if (editAlert) {
            setAlerts(prev => prev.map(a => a.id === result.id ? result : a));
          } else {
            setAlerts(prev => [result, ...prev]);
          }
          setModalOpen(false);
          setEditAlert(null);
        }}
        defaultFrom={profile?.corridor_from || "GBP"}
        defaultTo={profile?.corridor_to || "INR"}
        defaultAmount={1000}
        editAlert={editAlert}
        userWhatsapp={profile?.whatsapp_number}
      />

      <Footer />

      <style jsx>{`
        .alerts-page { padding: 3rem 0 6rem; min-height: 70vh; }
        .alerts-header {
          display: flex; align-items: flex-start; justify-content: space-between;
          gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap;
        }
        .alerts-section { margin-bottom: 2.5rem; }
        .section-title { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
        .count-pill {
          background: var(--secondary-dim); color: var(--secondary);
          font-size: 0.7rem; font-weight: 700; padding: 0.15rem 0.55rem;
          border-radius: var(--radius-full);
        }
        .count-muted { background: var(--surface-high); color: var(--muted); }
        .alerts-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 1rem; }
        .alerts-empty { text-align: center; padding: 4rem 2rem; }
        .empty-icon { font-size: 3rem; margin-bottom: 1rem; }
        .alerts-empty h2 { font-family: var(--font-display); font-weight: 700; font-size: 1.3rem; margin-bottom: 0.5rem; }
        .alerts-empty p { color: var(--muted); font-size: 0.875rem; }
      `}</style>
    </>
  );
}

function AlertCard({ alert, onToggle, onEdit, onDelete, deleting }) {
  const isActive = alert.is_active !== false;
  return (
    <div className={`ac-card card ${!isActive ? "ac-paused" : ""}`}>
      <div className="ac-header">
        <div className="ac-corridor">{alert.from_currency} → {alert.to_currency}</div>
        <span className={`pill ${isActive ? "pill-tertiary" : "pill-muted"}`}>
          {isActive ? "● Active" : "⏸ Paused"}
        </span>
      </div>
      <div className="ac-details">
        <div className="ac-row"><span className="ac-label">Target rate</span><span className="ac-val">{alert.target_rate}</span></div>
        <div className="ac-row"><span className="ac-label">Amount</span><span className="ac-val">{alert.amount} {alert.from_currency}</span></div>
        <div className="ac-row"><span className="ac-label">Provider</span><span className="ac-val">{alert.provider || "Any"}</span></div>
        <div className="ac-row">
          <span className="ac-label">Delivery</span>
          <span className="ac-val">{railLabel(alert.pay_out_method) || "Any"}</span>
        </div>
        <div className="ac-row"><span className="ac-label">Notify via</span>
          <span className="ac-val">
            {[alert.notify_email && "Email", alert.notify_whatsapp && "WhatsApp"].filter(Boolean).join(" + ") || "Email"}
          </span>
        </div>
        <div className="ac-row"><span className="ac-label">Created</span><span className="ac-val">{new Date(alert.created_at).toLocaleDateString()}</span></div>
      </div>
      <div className="ac-actions">
        <button className="btn-ghost-sm" onClick={() => onToggle(alert)} id={`toggle-alert-${alert.id}`}>
          {isActive ? "⏸ Pause" : "▶ Resume"}
        </button>
        <button className="btn-ghost-sm" onClick={() => onEdit(alert)} id={`edit-alert-${alert.id}`}>✏️ Edit</button>
        <button className="btn-ghost-sm ac-delete" onClick={() => onDelete(alert.id)} disabled={deleting} id={`delete-alert-${alert.id}`}>
          {deleting ? "…" : "🗑"}
        </button>
      </div>
      <style jsx>{`
        .ac-card { transition: box-shadow 0.2s; }
        .ac-paused { opacity: 0.7; }
        .ac-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
        .ac-corridor { font-family: var(--font-display); font-weight: 800; font-size: 1.2rem; color: var(--text); }
        .ac-details { display: flex; flex-direction: column; gap: 0.4rem; margin-bottom: 1rem; }
        .ac-row { display: flex; justify-content: space-between; font-size: 0.85rem; }
        .ac-label { color: var(--muted); }
        .ac-val { font-weight: 600; color: var(--text-mid); }
        .ac-actions { display: flex; gap: 0.5rem; }
        .ac-delete:hover:not(:disabled) { border-color: var(--error) !important; color: var(--error) !important; }
      `}</style>
    </div>
  );
}
