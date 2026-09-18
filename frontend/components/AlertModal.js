import { useState, useEffect, useRef } from "react";
import { useAuth } from "@clerk/nextjs";
import { CURRENCIES } from "../lib/currencies";
import { createAlert, updateAlert, listProviders } from "../lib/api";
import { railLabel } from "../lib/format";

/**
 * Delivery rails an alert can be scoped to. Canonical names, matching the ones
 * the backend normalizes every provider's vocabulary to (providers/rails.py).
 */
const PAYOUT_RAILS = [
  { value: "", label: "Any delivery method" },
  { value: "BANK_DEPOSIT", label: "Bank deposit" },
  { value: "UPI", label: "UPI" },
  { value: "CASH_PICKUP", label: "Cash pickup" },
  { value: "MOBILE_WALLET", label: "Mobile wallet" },
];

/**
 * AlertModal — create or edit a rate alert.
 *
 * Props:
 *   isOpen         {boolean}
 *   onClose        {() => void}
 *   onSuccess      {(alert) => void}  — called after save, receives the new/updated alert
 *   defaultFrom    {string}
 *   defaultTo      {string}
 *   defaultAmount  {number}
 *   editAlert      {object|null}  — if set, modal is in edit mode (uses PATCH)
 *   userWhatsapp   {string|null}  — if set, WhatsApp toggle is shown
 */
export default function AlertModal({
  isOpen,
  onClose,
  onSuccess,
  defaultFrom = "GBP",
  defaultTo = "INR",
  defaultAmount = 1000,
  editAlert = null,
  userWhatsapp = null,
}) {
  const { getToken } = useAuth();
  const modalRef = useRef(null);

  const [from, setFrom]               = useState(editAlert?.from_currency || defaultFrom);
  const [to, setTo]                   = useState(editAlert?.to_currency || defaultTo);
  const [amount, setAmount]           = useState(String(editAlert?.amount || defaultAmount));
  const [targetRate, setTargetRate]   = useState(String(editAlert?.target_rate || ""));
  const [provider, setProvider]       = useState(editAlert?.provider || "");
  const [payOut, setPayOut]           = useState(editAlert?.pay_out_method || "");
  // Loaded from the registry rather than hardcoded — a client-side list goes
  // stale silently and omits providers the engine is already comparing.
  const [providers, setProviders]     = useState([]);
  const [notifyEmail, setNotifyEmail] = useState(editAlert?.notify_email ?? true);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState("");

  // Reset state when modal opens for a new alert
  useEffect(() => {
    if (isOpen) {
      setFrom(editAlert?.from_currency || defaultFrom);
      setTo(editAlert?.to_currency || defaultTo);
      setAmount(String(editAlert?.amount || defaultAmount));
      setTargetRate(String(editAlert?.target_rate || ""));
      setProvider(editAlert?.provider || "");
      setPayOut(editAlert?.pay_out_method || "");
      setNotifyEmail(editAlert?.notify_email ?? true);
      setError("");
    }
  }, [isOpen, editAlert]);

  // Only the providers that actually serve this corridor: offering an alert on
  // one that does not would create a watch that can never fire.
  useEffect(() => {
    if (!isOpen || !from || !to || from === to) return;
    let cancelled = false;

    listProviders({ corridor: `${from}:${to}` })
      .then((data) => {
        if (cancelled) return;
        // Corridor alone is not enough. A provider that needs an unset API
        // key, only publishes a reference rate, or sits behind a JavaScript
        // calculator will never produce a quote — offering it would create
        // exactly the watch that can never fire.
        setProviders(
          (data?.providers || []).filter(
            (p) => p.is_configured && !p.rate_reference_only && !p.needs_browser
          )
        );
      })
      .catch(() => {
        // Non-critical: the alert still works scoped to "any provider".
        if (!cancelled) setProviders([]);
      });

    return () => { cancelled = true; };
  }, [isOpen, from, to]);

  // Close on backdrop click
  useEffect(() => {
    const handler = (e) => {
      if (modalRef.current && !modalRef.current.contains(e.target)) onClose();
    };
    if (isOpen) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen, onClose]);

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === "Escape") onClose(); };
    if (isOpen) document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    const parsedAmount = parseFloat(amount);
    const parsedRate   = parseFloat(targetRate);

    if (from === to) return setError("From and To currencies must be different.");
    if (!parsedAmount || parsedAmount <= 0) return setError("Enter a valid amount.");
    if (!parsedRate || parsedRate <= 0) return setError("Enter a valid target rate.");
    if (!notifyEmail) return setError("Email notification is required — it is the only delivery channel available right now.");

    const payload = {
      from_currency:   from,
      to_currency:     to,
      amount:          parsedAmount,
      target_rate:     parsedRate,
      provider:        provider || null,
      pay_out_method:  payOut || null,
      notify_email:    notifyEmail,
      notify_whatsapp: false,
    };

    setLoading(true);
    try {
      const token = await getToken();
      let result;
      if (editAlert) {
        result = await updateAlert(token, editAlert.id, payload);
      } else {
        result = await createAlert(token, payload);
      }
      onSuccess(result);
      onClose();
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-box" ref={modalRef} role="dialog" aria-modal="true">
        <div className="modal-header">
          <h2 className="modal-title">{editAlert ? "Edit Rate Alert" : "Create Rate Alert"}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <p className="modal-hint">
              We'll notify you when 1 {from} buys more than {targetRate || "___"} {to}
              {provider ? ` via ${provider}` : ""}
              {payOut ? ` to ${(railLabel(payOut) || "").toLowerCase()}` : ""}.
              {provider && (
                <>
                  {" "}We watch <strong>{provider}</strong>'s rate specifically — not
                  whichever provider happens to be cheapest.
                </>
              )}
            </p>

            {/* From / To */}
            <div className="modal-row">
              <div className="field">
                <label htmlFor="alert-from">From</label>
                <select id="alert-from" value={from} onChange={(e) => setFrom(e.target.value)}>
                  {CURRENCIES.map((c) => (
                    <option key={c.code} value={c.code}>{c.flag} {c.code}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="alert-to">To</label>
                <select id="alert-to" value={to} onChange={(e) => setTo(e.target.value)}>
                  {CURRENCIES.map((c) => (
                    <option key={c.code} value={c.code}>{c.flag} {c.code}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Amount + Target Rate */}
            <div className="modal-row">
              <div className="field">
                <label htmlFor="alert-amount">Amount</label>
                <input
                  id="alert-amount"
                  type="number"
                  min="1"
                  step="0.01"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="1000"
                />
              </div>
              <div className="field">
                <label htmlFor="alert-rate">Target rate (1 {from} → {to})</label>
                <input
                  id="alert-rate"
                  type="number"
                  min="0.000001"
                  step="0.000001"
                  value={targetRate}
                  onChange={(e) => setTargetRate(e.target.value)}
                  placeholder="e.g. 107.50"
                />
              </div>
            </div>

            {/* Provider */}
            <div className="field">
              <label htmlFor="alert-provider">Provider (optional)</label>
              <select id="alert-provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="">Any provider</option>
                {providers.map((p) => (
                  <option key={p.slug} value={p.name}>
                    {p.name}{p.avoid ? " (expensive)" : ""}
                  </option>
                ))}
              </select>
            </div>

            {/* Delivery rail */}
            <div className="field">
              <label htmlFor="alert-payout">Delivery method (optional)</label>
              <select id="alert-payout" value={payOut} onChange={(e) => setPayOut(e.target.value)}>
                {PAYOUT_RAILS.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>

            {/* Notification toggles */}
            <div className="modal-toggles">
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={notifyEmail}
                  onChange={(e) => setNotifyEmail(e.target.checked)}
                />
                <span>Notify by Email</span>
              </label>
              {userWhatsapp && (
                /* Disabled until there is something behind it. The backend
                   stores notify_whatsapp but nothing delivers it, so an alert
                   relying on it fires and notifies nobody. Offering a channel
                   that silently drops messages is worse than not offering it. */
                <label className="toggle-row toggle-row--disabled">
                  <input type="checkbox" checked={false} disabled readOnly />
                  <span>Notify by WhatsApp ({userWhatsapp}) — coming soon</span>
                </label>
              )}
            </div>

            {error && <p className="error-box" style={{ marginTop: "0.75rem" }}>{error}</p>}
          </div>

          <div className="modal-footer">
            <button type="button" className="btn-ghost" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button className="btn-compare" type="submit" disabled={loading} style={{ minWidth: 120 }}>
              {loading ? "Saving…" : editAlert ? "Save Changes" : "Create Alert"}
            </button>
          </div>
        </form>
      </div>

      <style jsx>{`
        .modal-backdrop {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(0,0,0,0.7);
          display: flex; align-items: center; justify-content: center;
          padding: 1rem;
        }
        .modal-box {
          background: var(--surface);
          border: 1px solid var(--border2);
          border-radius: 14px;
          width: 100%; max-width: 480px;
          overflow: hidden;
        }
        .modal-header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 1.25rem 1.5rem;
          border-bottom: 1px solid var(--border);
        }
        .modal-title {
          font-family: var(--font-sans);
          font-size: 1rem; font-weight: 700; color: var(--text);
        }
        .modal-close {
          background: none; border: none; color: var(--muted);
          font-size: 1.5rem; cursor: pointer; line-height: 1;
          padding: 0 0.25rem;
        }
        .modal-close:hover { color: var(--text); }
        .modal-hint {
          font-size: 0.8rem; color: var(--muted);
          margin-bottom: 1rem;
          padding: 0.6rem 0.9rem;
          border: 1px solid var(--border);
          border-radius: 7px;
          background: var(--bg);
        }
        .modal-body { padding: 1.25rem 1.5rem; }
        .modal-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
        @media (max-width: 400px) { .modal-row { grid-template-columns: 1fr; } }
        .modal-toggles { margin-top: 1rem; display: flex; flex-direction: column; gap: 0.5rem; }
        .toggle-row {
          display: flex; align-items: center; gap: 0.6rem;
          font-size: 0.85rem; color: var(--text); cursor: pointer;
        }
        .toggle-row input[type="checkbox"] { accent-color: var(--spark); width: 15px; height: 15px; }
        .toggle-row--disabled { color: var(--muted); cursor: not-allowed; }
        .modal-footer {
          display: flex; gap: 0.75rem; justify-content: flex-end;
          padding: 1rem 1.5rem;
          border-top: 1px solid var(--border);
        }
        .btn-ghost {
          background: none; border: 1px solid var(--border2);
          color: var(--muted); font-family: var(--font-sans);
          font-size: 0.85rem; font-weight: 600;
          padding: 0.65rem 1.1rem; border-radius: 7px; cursor: pointer;
          transition: border-color 0.15s, color 0.15s;
        }
        .btn-ghost:hover:not(:disabled) { border-color: var(--muted); color: var(--text); }
      `}</style>
    </div>
  );
}
