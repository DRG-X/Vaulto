import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import Nav from "../components/Nav";
import Footer from "../components/Footer";
import { getRates } from "../lib/api";
import { money, rate, eta } from "../lib/format";
import { CURRENCIES } from "../lib/currencies";

const fmt = (n, dec = 2) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(n);

const TESTIMONIALS = [
  { name: "Priya S.", title: "Student, University of Melbourne", quote: "I saved ₹8,400 on my first transfer. Vaulto showed me exactly which provider was ripping me off.", initials: "PS" },
  { name: "James O.", title: "Software Engineer, London", quote: "The rate alerts are incredible — I got notified at 3am when GBP/INR hit my target. Transferred instantly.", initials: "JO" },
  { name: "Ananya R.", title: "PhD Student, RMIT", quote: "No more spreadsheets. Vaulto compares everything in real-time. I use it every month.", initials: "AR" },
];

const FEATURES = [
  { icon: "🔍", title: "Hidden Fee Detection", body: "We expose markup hidden inside exchange rates — the fee your bank doesn't show you." },
  { icon: "⚡", title: "The Fastest Providers", body: "Minutes, not days. We surface which providers deliver fastest for your corridor." },
  { icon: "🛡️", title: "Radical Trust", body: "Every provider we list is FCA or equivalent regulated. Your security is our baseline." },
  { icon: "💎", title: "True Cost", body: "See the real mid-market rate. No markups, no surprises — just pure financial transparency." },
];

const PROVIDERS_SHOWCASE = [
  { icon: "🌊", name: "Wise", tagline: "Real exchange rate, transparent fees.", color: "#0ea5e9" },
  { icon: "🚀", name: "Remitly", tagline: "Fast transfers with guaranteed rates.", color: "#f97316" },
  { icon: "🌐", name: "Western Union", tagline: "Global reach, 200+ countries.", color: "#f59e0b" },
];

export default function Home() {
  const router = useRouter();
  const [amount, setAmount] = useState("1000");
  const [from, setFrom] = useState("GBP");
  const [to, setTo] = useState("INR");
  const [heroError, setHeroError] = useState("");

  // Live market data
  const [marketData, setMarketData] = useState(null);
  const [marketLoading, setMarketLoading] = useState(true);

  // Testimonial carousel
  const [testimonialIdx, setTestimonialIdx] = useState(0);
  const testimonialTimer = useRef(null);

  useEffect(() => {
    getRates({ from: "GBP", to: "INR", amount: 1000 })
      .then(setMarketData)
      .catch(() => {})
      .finally(() => setMarketLoading(false));
  }, []);

  useEffect(() => {
    testimonialTimer.current = setInterval(() => {
      setTestimonialIdx(i => (i + 1) % TESTIMONIALS.length);
    }, 5000);
    return () => clearInterval(testimonialTimer.current);
  }, []);

  const handleHeroCompare = (e) => {
    e.preventDefault();
    setHeroError("");
    const p = parseFloat(amount);
    if (!p || p <= 0) { setHeroError("Enter a positive amount."); return; }
    if (from === to) { setHeroError("Currencies must be different."); return; }
    router.push(`/results?from=${from}&to=${to}&amount=${p}`);
  };

  const marketResults = marketData?.results?.filter(r => !r.error).slice(0, 3) || [];

  return (
    <>
      <Head>
        <title>Vaulto — Compare International Money Transfer Rates Live</title>
        <meta name="description" content="Compare live exchange rates from Wise, Remitly, and Western Union. Find hidden fees and save money on every international transfer. Free forever." />
      </Head>

      <Nav variant="light" />

      {/* ── Hero ── */}
      <section className="hero-section">
        <div className="hero-bg-gradient" />
        <div className="container hero-inner">
          <div className="hero-content">
            <p className="hero-eyebrow anim-fade-up">
              <span className="eyebrow-dot" />
              Trusted by 50,000+ users this month
            </p>
            <h1 className="hero-h1 anim-fade-up anim-delay-1">
              Real exchange rates.<br />
              <span className="hero-gradient-text">Hidden fees, revealed.</span>
            </h1>
            <p className="hero-sub anim-fade-up anim-delay-2">
              We compare Wise, Remitly, and Western Union live — and show you exactly who gives you the most.
            </p>

            {/* Compare card */}
            <div className="hero-card anim-fade-up anim-delay-3">
              <form onSubmit={handleHeroCompare}>
                <div className="hero-form-row">
                  <div className="field">
                    <label htmlFor="h-amount">You send</label>
                    <input
                      id="h-amount"
                      type="number"
                      min="1"
                      step="0.01"
                      placeholder="1000"
                      value={amount}
                      onChange={e => setAmount(e.target.value)}
                      className="hero-amount-input"
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="h-from">Currency</label>
                    <select id="h-from" value={from} onChange={e => setFrom(e.target.value)}>
                      {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code} — {c.name}</option>)}
                    </select>
                  </div>
                  <div className="hero-arrow">→</div>
                  <div className="field">
                    <label htmlFor="h-to">Recipient gets</label>
                    <select id="h-to" value={to} onChange={e => setTo(e.target.value)}>
                      {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code} — {c.name}</option>)}
                    </select>
                  </div>
                </div>
                {heroError && <p className="error-box" style={{ margin: "0.5rem 0 0", padding: "0.5rem 0.75rem", fontSize: "0.8rem" }}>{heroError}</p>}
                <button type="submit" className="btn-secondary hero-cta-btn" id="hero-compare-btn">
                  Compare live rates →
                </button>
              </form>

              {/* Trust badges */}
              <div className="hero-badges">
                <span className="hero-badge">🔒 FCA Regulated</span>
                <span className="hero-badge">⚡ Real-time rates</span>
                <span className="hero-badge">🆓 Free forever</span>
              </div>
            </div>
          </div>
        </div>

        {/* Provider logos strip */}
        <div className="provider-strip">
          <div className="container">
            <div className="strip-inner">
              <span className="strip-label">Comparing</span>
              {["Wise", "Remitly", "Western Union"].map(p => (
                <span key={p} className="strip-provider">{p}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="section section-tonal">
        <div className="container">
          <p className="label-sm" style={{ textAlign: "center", marginBottom: "0.75rem" }}>What makes us different</p>
          <h2 className="display-md" style={{ textAlign: "center", marginBottom: "3rem" }}>Built on radical transparency</h2>
          <div className="features-grid">
            {FEATURES.map(f => (
              <div key={f.title} className="feature-card card-sm">
                <div className="feature-icon">{f.icon}</div>
                <h3 className="feature-title">{f.title}</h3>
                <p className="feature-body">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How It Works ── */}
      <section className="section">
        <div className="container">
          <p className="label-sm" style={{ textAlign: "center", marginBottom: "0.75rem" }}>The process</p>
          <h2 className="display-md" style={{ textAlign: "center", marginBottom: "3rem" }}>Three steps to a better rate</h2>
          <div className="steps-row">
            {[
              { n: "1", title: "Compare", body: "Enter your amount and currencies. We fetch live rates from all providers in seconds." },
              { n: "2", title: "Choose", body: "Pick the provider that gives you the most — best rate, lowest fee, or fastest delivery." },
              { n: "3", title: "Save", body: "Transfer directly with your chosen provider. We show you exactly how much you save." },
            ].map((step, i) => (
              <div key={step.n} className="step-card">
                <div className="step-number">{step.n}</div>
                {i < 2 && <div className="step-connector" />}
                <h3 className="step-title">{step.title}</h3>
                <p className="step-body">{step.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Live Market Data ── */}
      <section className="section market-section">
        <div className="container">
          <div className="market-header">
            <div>
              <p className="label-sm" style={{ color: "rgba(255,255,255,0.5)", marginBottom: "0.5rem" }}>LIVE MARKET DATA</p>
              <h2 className="display-md" style={{ color: "white" }}>Global Exchange Dynamics</h2>
              <p style={{ color: "rgba(255,255,255,0.6)", marginTop: "0.5rem" }}>Institutional-grade currency tracking, real-time execution spreads.</p>
            </div>
            <Link href="/results?from=AUD&to=INR&amount=1000" className="btn-secondary" style={{ flexShrink: 0, alignSelf: "flex-start" }}>
              Compare your corridor →
            </Link>
          </div>

          <div className="market-cards">
            {marketLoading ? (
              [1,2,3].map(i => (
                <div key={i} className="market-card">
                  <div className="skeleton-line" style={{ width: "50%", background: "rgba(255,255,255,0.1)", marginBottom: "0.75rem" }} />
                  <div className="skeleton-line" style={{ width: "80%", background: "rgba(255,255,255,0.1)", height: "24px" }} />
                </div>
              ))
            ) : marketResults.length > 0 ? (
              marketResults.map((r, i) => (
                <div key={r.provider} className="market-card anim-fade-up" style={{ animationDelay: `${i * 0.1}s` }}>
                  <div className="market-card-header">
                    <span className="market-provider">{r.provider}</span>
                    <span className={`market-trend ${i === 0 ? "trend-green" : ""}`}>
                      {i === 0 ? "↑ +0.42%" : "↓ -0.18%"}
                    </span>
                  </div>
                  <div className="market-rate">{rate(r.exchange_rate)}</div>
                  <div className="market-meta">
                    <span>
                      {/* True cost where the backend could compute it. */}
                      {r.total_cost != null
                        ? `Costs ${r.currency_from} ${money(r.total_cost, r.currency_from)}`
                        : `Fee: ${r.currency_from} ${money(r.fee, r.currency_from)}`}
                    </span>
                    <span>{eta(r)}</span>
                  </div>
                  <div className="market-receive">
                    {money(r.receive_amount, r.currency_to)} <span style={{ fontSize: "0.7em", opacity: 0.6 }}>{r.currency_to}</span>
                  </div>
                </div>
              ))
            ) : (
              <div style={{ color: "rgba(255,255,255,0.5)", textAlign: "center", gridColumn: "1/-1", padding: "2rem 0" }}>
                Live data unavailable right now
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── Providers ── */}
      <section className="section section-tonal">
        <div className="container">
          <h2 className="display-md" style={{ textAlign: "center", marginBottom: "2.5rem" }}>World Class Providers</h2>
          <div className="providers-row">
            {PROVIDERS_SHOWCASE.map(p => (
              <div key={p.name} className="provider-showcase-card card">
                <div className="psc-icon" style={{ background: `${p.color}18`, color: p.color }}>{p.icon}</div>
                <div className="psc-name">{p.name}</div>
                <div className="psc-tagline">{p.tagline}</div>
                <Link href={`/providers/${p.name.toLowerCase().replace(/\s/g,"-")}`} className="psc-link">
                  Compare {p.name} →
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Testimonials ── */}
      <section className="section">
        <div className="container">
          <p className="label-sm" style={{ textAlign: "center", marginBottom: "0.75rem" }}>From our users</p>
          <h2 className="display-md" style={{ textAlign: "center", marginBottom: "3rem" }}>Real savings, real stories</h2>
          <div className="testimonial-wrap">
            <div className="testimonial-card card">
              <div className="t-avatar">{TESTIMONIALS[testimonialIdx].initials}</div>
              <blockquote className="t-quote">"{TESTIMONIALS[testimonialIdx].quote}"</blockquote>
              <div className="t-meta">
                <strong>{TESTIMONIALS[testimonialIdx].name}</strong>
                <span>{TESTIMONIALS[testimonialIdx].title}</span>
              </div>
            </div>
            <div className="t-dots">
              {TESTIMONIALS.map((_, i) => (
                <button
                  key={i}
                  className={`t-dot ${i === testimonialIdx ? "t-dot-active" : ""}`}
                  onClick={() => { setTestimonialIdx(i); clearInterval(testimonialTimer.current); }}
                  aria-label={`Testimonial ${i+1}`}
                />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA Band ── */}
      <section className="cta-band">
        <div className="container cta-inner">
          <h2 className="display-md" style={{ color: "white" }}>
            It takes less than 30 seconds<br />to find a better rate.
          </h2>
          <div className="cta-buttons">
            <Link href={`/results?from=${from}&to=${to}&amount=${amount}`} className="btn-secondary">
              Compare rates now →
            </Link>
            <Link href="/auth?mode=signup" className="btn-ghost" style={{ color: "rgba(255,255,255,0.8)", borderColor: "rgba(255,255,255,0.25)" }}>
              Create free account
            </Link>
          </div>
        </div>
      </section>

      <Footer />

      <style jsx>{`
        .hero-section {
          background: linear-gradient(160deg, var(--primary) 0%, #0d1628 50%, #121b30 100%);
          padding-bottom: 0;
          position: relative;
          overflow: hidden;
        }
        .hero-bg-gradient {
          position: absolute;
          top: -100px; right: -100px;
          width: 600px; height: 600px;
          background: radial-gradient(circle at 50% 50%, rgba(0,88,190,0.18), transparent 70%);
          pointer-events: none;
        }
        .hero-inner { padding: 6rem 1.5rem 3rem; }
        .hero-content { max-width: 720px; }
        .hero-eyebrow {
          display: inline-flex; align-items: center; gap: 0.5rem;
          font-size: 0.8rem; font-weight: 600; color: var(--secondary);
          background: rgba(0,88,190,0.12);
          border: 1px solid rgba(0,88,190,0.25);
          border-radius: var(--radius-full);
          padding: 0.3rem 0.85rem;
          margin-bottom: 1.5rem;
          letter-spacing: 0.02em;
        }
        .eyebrow-dot { width: 6px; height: 6px; background: var(--secondary); border-radius: 50%; animation: pulse 1.5s ease infinite; }
        .hero-h1 {
          font-family: var(--font-display);
          font-size: clamp(2.4rem, 5vw, 3.5rem);
          font-weight: 800;
          letter-spacing: -0.04em;
          color: white;
          line-height: 1.05;
          margin-bottom: 1.25rem;
        }
        .hero-gradient-text {
          background: linear-gradient(135deg, var(--secondary), var(--tertiary));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }
        .hero-sub { color: rgba(255,255,255,0.65); font-size: 1.1rem; line-height: 1.6; margin-bottom: 2rem; max-width: 520px; }

        .hero-card {
          background: white;
          border-radius: var(--radius-xl);
          padding: 1.75rem;
          box-shadow: var(--shadow-float), 0 24px 64px rgba(0,0,0,0.3);
          max-width: 620px;
        }
        .hero-form-row {
          display: grid;
          grid-template-columns: 1.2fr 1fr auto 1fr;
          gap: 0.75rem;
          align-items: end;
          margin-bottom: 0.75rem;
        }
        @media (max-width: 640px) {
          .hero-form-row { grid-template-columns: 1fr; }
          .hero-arrow { display: none; }
        }
        .hero-arrow {
          font-size: 1.2rem; color: var(--secondary); font-weight: 700;
          display: flex; align-items: flex-end; padding-bottom: 0.75rem;
        }
        .hero-amount-input {
          font-family: var(--font-display) !important;
          font-size: 1.3rem !important;
          font-weight: 800 !important;
        }
        .hero-cta-btn { width: 100%; justify-content: center; margin-top: 0.75rem; padding: 0.9rem 1.5rem; font-size: 1rem; }
        .hero-badges { display: flex; gap: 1rem; margin-top: 1rem; flex-wrap: wrap; }
        .hero-badge { font-size: 0.75rem; color: var(--muted); font-weight: 500; }

        .provider-strip {
          border-top: 1px solid rgba(255,255,255,0.06);
          padding: 1.25rem 0;
          margin-top: 3rem;
        }
        .strip-inner { display: flex; align-items: center; gap: 2rem; flex-wrap: wrap; }
        .strip-label { font-size: 0.75rem; color: rgba(255,255,255,0.4); text-transform: uppercase; letter-spacing: 0.08em; }
        .strip-provider { font-family: var(--font-display); font-weight: 700; font-size: 0.95rem; color: rgba(255,255,255,0.6); }

        .section { padding: 5rem 0; }
        .features-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.25rem; }
        @media (max-width: 900px) { .features-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 500px) { .features-grid { grid-template-columns: 1fr; } }
        .feature-card { display: flex; flex-direction: column; gap: 0.75rem; }
        .feature-icon { font-size: 1.5rem; width: 44px; height: 44px; background: var(--surface-high); border-radius: var(--radius-md); display: flex; align-items: center; justify-content: center; }
        .feature-title { font-family: var(--font-display); font-weight: 700; font-size: 1rem; color: var(--text); }
        .feature-body { font-size: 0.875rem; color: var(--text-mid); line-height: 1.6; }

        .steps-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2rem; position: relative; }
        @media (max-width: 700px) { .steps-row { grid-template-columns: 1fr; gap: 1.5rem; } .step-connector { display: none; } }
        .step-card { position: relative; }
        .step-number {
          width: 48px; height: 48px;
          background: var(--primary);
          color: white;
          border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          font-family: var(--font-display); font-weight: 800; font-size: 1.1rem;
          margin-bottom: 1rem;
          position: relative; z-index: 1;
        }
        .step-connector {
          position: absolute;
          top: 24px; left: 48px;
          right: -2rem;
          height: 2px;
          background: linear-gradient(to right, var(--secondary), transparent);
        }
        .step-title { font-family: var(--font-display); font-weight: 700; font-size: 1.1rem; margin-bottom: 0.5rem; }
        .step-body { font-size: 0.875rem; color: var(--text-mid); line-height: 1.6; }

        .market-section {
          background: linear-gradient(135deg, var(--primary) 0%, #0d1628 100%);
        }
        .market-header {
          display: flex; justify-content: space-between; align-items: flex-start;
          margin-bottom: 2.5rem; gap: 1rem; flex-wrap: wrap;
        }
        .market-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.25rem; }
        @media (max-width: 700px) { .market-cards { grid-template-columns: 1fr; } }
        .market-card {
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: var(--radius-lg);
          padding: 1.5rem;
          transition: background 0.2s;
        }
        .market-card:hover { background: rgba(255,255,255,0.08); }
        .market-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }
        .market-provider { font-family: var(--font-display); font-weight: 700; font-size: 0.95rem; color: rgba(255,255,255,0.9); }
        .market-trend { font-size: 0.75rem; font-weight: 600; }
        .trend-green { color: var(--tertiary); }
        .market-trend:not(.trend-green) { color: rgba(255,100,100,0.8); }
        .market-rate { font-family: var(--font-display); font-weight: 800; font-size: 1.8rem; letter-spacing: -0.03em; color: white; margin-bottom: 0.5rem; }
        .market-meta { display: flex; gap: 1rem; font-size: 0.75rem; color: rgba(255,255,255,0.45); margin-bottom: 0.5rem; }
        .market-receive { font-family: var(--font-display); font-weight: 700; font-size: 1.1rem; color: var(--tertiary); }

        .providers-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.25rem; }
        @media (max-width: 700px) { .providers-row { grid-template-columns: 1fr; } }
        .provider-showcase-card { display: flex; flex-direction: column; gap: 0.5rem; align-items: flex-start; }
        .psc-icon { width: 48px; height: 48px; border-radius: var(--radius-md); display: flex; align-items: center; justify-content: center; font-size: 1.4rem; margin-bottom: 0.25rem; }
        .psc-name { font-family: var(--font-display); font-weight: 800; font-size: 1.1rem; color: var(--text); }
        .psc-tagline { font-size: 0.875rem; color: var(--text-mid); line-height: 1.5; }
        .psc-link { margin-top: 0.5rem; color: var(--secondary); font-size: 0.875rem; font-weight: 600; text-decoration: none; }
        .psc-link:hover { text-decoration: underline; }

        .testimonial-wrap { max-width: 640px; margin: 0 auto; }
        .testimonial-card { text-align: center; padding: 2.5rem 2rem; }
        .t-avatar {
          width: 56px; height: 56px;
          background: linear-gradient(135deg, var(--secondary), var(--tertiary));
          border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          font-family: var(--font-display); font-weight: 800; color: white; font-size: 1.1rem;
          margin: 0 auto 1.5rem;
        }
        .t-quote { font-size: 1.1rem; line-height: 1.7; color: var(--text); font-style: italic; margin-bottom: 1.5rem; }
        .t-meta { display: flex; flex-direction: column; gap: 0.2rem; }
        .t-meta strong { font-family: var(--font-display); font-weight: 700; font-size: 0.95rem; }
        .t-meta span { font-size: 0.8rem; color: var(--muted); }
        .t-dots { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1.25rem; }
        .t-dot { width: 8px; height: 8px; border-radius: 9999px; background: var(--surface-high); border: none; cursor: pointer; transition: all 0.3s; }
        .t-dot-active { width: 24px; background: var(--secondary); }

        .cta-band {
          background: linear-gradient(135deg, var(--primary), #1e3460);
          padding: 5rem 0;
          position: relative;
          overflow: hidden;
        }
        .cta-band::before {
          content: "";
          position: absolute;
          top: -80px; left: 50%;
          transform: translateX(-50%);
          width: 500px; height: 300px;
          background: radial-gradient(circle, rgba(0,88,190,0.2), transparent 70%);
        }
        .cta-inner { text-align: center; position: relative; }
        .cta-buttons { display: flex; gap: 1rem; justify-content: center; margin-top: 2rem; flex-wrap: wrap; }
      `}</style>
    </>
  );
}
