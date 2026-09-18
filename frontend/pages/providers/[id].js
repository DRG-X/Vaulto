import { useState, useEffect } from "react";
import Head from "next/head";
import Link from "next/link";
import Nav from "../../components/Nav";
import Footer from "../../components/Footer";
import { getRates } from "../../lib/api";
import { money, rate, eta } from "../../lib/format";

const PROVIDER_DATA = {
  wise: {
    name: "Wise",
    icon: "🌊",
    color: "#0ea5e9",
    tagline: "Real exchange rates, transparent fees.",
    rating: "4.8",
    openAccountUrl: "https://wise.com",
    description: "Wise uses the real mid-market exchange rate — the one you see on Google — and charges a small, transparent fee. No hidden markups inside the rate.",
    pros: ["Real mid-market exchange rate", "Multi-currency account", "FCA regulated", "160+ countries supported"],
    cons: ["Limited cash pickup", "Higher fees for large amounts", "Stricter ID verification", "No agent pickup network"],
    steps: ["Create Account", "Enter Amount", "Recipient Details", "Fund & Send"],
    alternatives: ["Remitly", "Western Union"],
  },
  remitly: {
    name: "Remitly",
    icon: "🚀",
    color: "#f97316",
    tagline: "Fast transfers with guaranteed delivery.",
    rating: "4.6",
    openAccountUrl: "https://remitly.com",
    description: "Remitly specialises in consumer remittances, with competitive rates and a delivery promise. Multiple payout options including bank deposit and cash pickup.",
    pros: ["Guaranteed delivery promise", "Cash pickup available", "Mobile-first experience", "Promo rates for new users"],
    cons: ["Limited transfer size", "Rates vary by corridor", "Add transfer fees", "Stricter limits for new users"],
    steps: ["Sign Up", "Enter Amount", "Add Recipient", "Fund & Track"],
    alternatives: ["Wise", "Western Union"],
  },
  "western-union": {
    name: "Western Union",
    icon: "🌐",
    color: "#f59e0b",
    tagline: "Global reach. 200+ countries and territories.",
    rating: "4.2",
    openAccountUrl: "https://westernunion.com",
    description: "Western Union offers unmatched global reach. Best for sending to remote destinations where digital providers don't operate, with cash pickup at 500,000+ agent locations.",
    pros: ["Real mid-market exchange rate", "500K+ agent locations", "Cash pickup anywhere", "Multiple payment methods"],
    cons: ["Higher fees overall", "Exchange rate markup", "Slow bank transfers", "Agent-dependent for cash"],
    steps: ["Check Account", "Enter Amount", "Recipient Details", "Pay & Finish"],
    alternatives: ["Wise", "Remitly"],
  },
};

const fmt = (n, dec = 2) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(n);

export default function ProviderDetail({ id }) {
  const provider = PROVIDER_DATA[id];
  const [rateData, setRateData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getRates({ from: "GBP", to: "INR", amount: 1000 })
      .then(setRateData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (!provider) {
    return (
      <><Nav variant="light" />
        <div className="container" style={{ padding: "8rem 1.5rem", textAlign: "center" }}>
          <h1>Provider not found</h1>
          <Link href="/providers" className="btn-secondary" style={{ marginTop: "1rem", display: "inline-flex" }}>← Browse Providers</Link>
        </div>
        <Footer />
      </>
    );
  }

  const liveResult = rateData?.results?.find(r => r.provider === provider.name);

  return (
    <>
      <Head>
        <title>{provider.name} Review — Vaulto</title>
        <meta name="description" content={`${provider.name}: ${provider.tagline} Compare live rates and fees with Vaulto.`} />
      </Head>
      <Nav variant="light" />

      {/* Hero */}
      <section className="pd-hero">
        <div className="container">
          <p className="label-sm" style={{ marginBottom: "0.75rem" }}>
            <Link href="/providers" style={{ color: "var(--secondary)", textDecoration: "none" }}>← All Providers</Link>
          </p>
          <div className="pd-hero-inner">
            <div className="pd-hero-left">
              <div className="pd-icon" style={{ background: `${provider.color}18`, color: provider.color }}>{provider.icon}</div>
              <div>
                <h1 className="display-md">{provider.name}</h1>
                <p style={{ color: "var(--muted)", marginTop: "0.35rem" }}>{provider.tagline}</p>
                <div className="pd-rating">{"★".repeat(Math.floor(parseFloat(provider.rating)))} <strong>{provider.rating}</strong></div>
              </div>
            </div>
            <a href={provider.openAccountUrl} target="_blank" rel="noopener noreferrer" className="btn-secondary">
              Open Free Account ↗
            </a>
          </div>
        </div>
      </section>

      <div className="container pd-layout">
        <main className="pd-main">
          {/* Live rate card */}
          <div className="card pd-live-card" style={{ marginBottom: "1.5rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <p className="label-sm">Live GBP → INR Rate (calculated for 1,000 GBP)</p>
              <span className="pill pill-secondary">⚡ Live</span>
            </div>
            {loading ? (
              <div className="skeleton-line" style={{ height: 48, width: "50%" }} />
            ) : liveResult ? (
              <div>
                <div style={{ fontFamily: "var(--font-display)", fontSize: "2.5rem", fontWeight: 800, color: "var(--tertiary)", letterSpacing: "-0.03em" }}>
                  {money(liveResult.receive_amount, liveResult.currency_to)} <span style={{ fontSize: "1rem", color: "var(--muted)" }}>{liveResult.currency_to}</span>
                </div>
                <div style={{ display: "flex", gap: "1.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
                  <div><span className="label-sm">Exchange Rate</span><br /><strong>{rate(liveResult.exchange_rate)}</strong></div>
                  <div><span className="label-sm">Upfront fee</span><br /><strong>{liveResult.currency_from} {money(liveResult.fee, liveResult.currency_from)}</strong></div>
                  {liveResult.total_cost != null && (
                    <div>
                      {/* Fee plus the markup buried in the rate. */}
                      <span className="label-sm">True cost</span><br />
                      <strong>{liveResult.currency_from} {money(liveResult.total_cost, liveResult.currency_from)}</strong>
                    </div>
                  )}
                  <div><span className="label-sm">Delivery</span><br /><strong>{eta(liveResult)}</strong></div>
                </div>
              </div>
            ) : (
              <p style={{ color: "var(--muted)" }}>Live rate unavailable. <Link href={`/results?from=GBP&to=INR&amount=1000`} style={{ color: "var(--secondary)" }}>Try comparison →</Link></p>
            )}
          </div>

          {/* Pros & Cons */}
          <div className="card" style={{ marginBottom: "1.5rem" }}>
            <h2 className="headline" style={{ marginBottom: "1.25rem" }}>The Advantage</h2>
            <div className="pros-cons-grid">
              <div>
                <p className="label-sm" style={{ color: "var(--tertiary)", marginBottom: "0.75rem" }}>✓ The Advantage</p>
                <ul className="pros-list">
                  {provider.pros.map(p => <li key={p}><span className="pro-icon">✓</span>{p}</li>)}
                </ul>
              </div>
              <div>
                <p className="label-sm" style={{ color: "var(--error)", marginBottom: "0.75rem" }}>⚠ Considerations</p>
                <ul className="cons-list">
                  {provider.cons.map(c => <li key={c}><span className="con-icon">✗</span>{c}</li>)}
                </ul>
              </div>
            </div>
          </div>

          {/* How to send */}
          <div className="card" style={{ marginBottom: "1.5rem" }}>
            <h2 className="headline" style={{ marginBottom: "1.25rem" }}>How to send with {provider.name}</h2>
            <div className="steps-row">
              {provider.steps.map((step, i) => (
                <div key={step} className="pd-step">
                  <div className="pd-step-num" style={{ background: i === provider.steps.length - 1 ? provider.color : "var(--primary)" }}>{i + 1}</div>
                  <div className="pd-step-label">{step}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Compare alternatives */}
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h2 className="headline">Compare Alternatives</h2>
              <Link href="/results?from=GBP&to=INR&amount=1000" className="btn-ghost" style={{ fontSize: "0.85rem" }}>View Full Table →</Link>
            </div>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              {provider.alternatives.map(alt => (
                <Link key={alt} href={`/providers/${alt.toLowerCase().replace(/\s/g,"-")}`} className="btn-ghost" style={{ fontSize: "0.875rem" }}>
                  {alt} →
                </Link>
              ))}
            </div>
          </div>
        </main>

        <aside className="pd-sidebar">
          <div className="card" style={{ marginBottom: "1.25rem" }}>
            <p className="label-sm" style={{ marginBottom: "0.75rem" }}>About</p>
            <p style={{ fontSize: "0.875rem", color: "var(--text-mid)", lineHeight: 1.6 }}>{provider.description}</p>
          </div>
          <div className="card">
            <p className="label-sm" style={{ marginBottom: "0.75rem" }}>Compare all providers</p>
            <p style={{ fontSize: "0.875rem", color: "var(--muted)", marginBottom: "1rem" }}>
              See how {provider.name} stacks up against every other provider in real-time.
            </p>
            <Link href="/results?from=GBP&to=INR&amount=1000" className="btn-secondary" style={{ width: "100%", justifyContent: "center" }}>
              Compare now →
            </Link>
          </div>
        </aside>
      </div>

      <Footer />

      <style jsx>{`
        .pd-hero { background: var(--surface-low); padding: 3rem 0 2.5rem; border-bottom: 1px solid var(--surface-high); }
        .pd-hero-inner { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; flex-wrap: wrap; margin-top: 1rem; }
        .pd-hero-left { display: flex; align-items: flex-start; gap: 1.25rem; }
        .pd-icon { width: 56px; height: 56px; border-radius: var(--radius-lg); display: flex; align-items: center; justify-content: center; font-size: 1.75rem; flex-shrink: 0; }
        .pd-rating { margin-top: 0.4rem; font-size: 0.9rem; color: #f59e0b; }
        .pd-rating strong { color: var(--text); margin-left: 0.25rem; }

        .pd-layout { display: grid; grid-template-columns: 1fr 280px; gap: 1.5rem; padding: 2rem 1.5rem 5rem; align-items: start; }
        @media (max-width: 900px) { .pd-layout { grid-template-columns: 1fr; } }

        .pd-live-card { border-left: 3px solid var(--tertiary); }

        .pros-cons-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
        @media (max-width: 600px) { .pros-cons-grid { grid-template-columns: 1fr; } }
        .pros-list, .cons-list { list-style: none; display: flex; flex-direction: column; gap: 0.6rem; }
        .pros-list li, .cons-list li { display: flex; align-items: flex-start; gap: 0.6rem; font-size: 0.875rem; color: var(--text-mid); line-height: 1.4; }
        .pro-icon { color: var(--tertiary); font-weight: 700; flex-shrink: 0; }
        .con-icon { color: var(--error); font-weight: 700; flex-shrink: 0; }

        .steps-row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
        .pd-step { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; min-width: 80px; text-align: center; }
        .pd-step-num { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-family: var(--font-display); font-weight: 800; font-size: 1rem; }
        .pd-step-label { font-size: 0.75rem; color: var(--text-mid); font-weight: 500; }
      `}</style>
    </>
  );
}

export async function getStaticPaths() {
  return {
    paths: [
      { params: { id: "wise" } },
      { params: { id: "remitly" } },
      { params: { id: "western-union" } },
    ],
    fallback: false,
  };
}

export async function getStaticProps({ params }) {
  return { props: { id: params.id } };
}
