import { useState } from "react";
import Head from "next/head";
import Link from "next/link";
import Nav from "../components/Nav";
import Footer from "../components/Footer";
import ProviderDirectory from "../components/ProviderDirectory";

const PROVIDERS = [
  {
    id: "wise",
    icon: "🌊",
    name: "Wise",
    color: "#0ea5e9",
    tagline: "Real exchange rate, transparent fees. No hidden markups.",
    description: "Wise (formerly TransferWise) uses the real mid-market exchange rate for all transfers and charges a small, upfront fee. No surprise markups in the rate.",
    avgFee: "0.5–1.5%",
    speed: "Instant–2 hours",
    regulated: "FCA (UK), FinCEN (US), ASIC (AU)",
    features: ["Real mid-market rate", "Multi-currency account", "Debit card included", "Mass payments API", "160+ countries"],
    bestFor: ["Freelancers & remote workers", "Multi-currency businesses", "Regular international transfers"],
  },
  {
    id: "remitly",
    icon: "🚀",
    name: "Remitly",
    color: "#f97316",
    tagline: "Fast, guaranteed rates with a delivery promise.",
    description: "Remitly specialises in consumer remittances with competitive rates, a delivery guarantee, and multiple payout options including bank deposit and cash pickup.",
    avgFee: "1–3%",
    speed: "Minutes–3 days",
    regulated: "FinCEN (US), FCA (UK)",
    features: ["Guaranteed delivery promise", "Cash pickup option", "Mobile-first experience", "Promo rates for new users", "170+ countries"],
    bestFor: ["First-time senders", "Sending to family abroad", "Cash pickup recipients"],
  },
  {
    id: "western-union",
    icon: "🌐",
    name: "Western Union",
    color: "#f59e0b",
    tagline: "Global reach in 200+ countries and territories.",
    description: "Western Union is the largest global money transfer network, offering unmatched reach. Best for sending to remote locations where digital providers don't operate.",
    avgFee: "2–5%",
    speed: "Minutes (cash), 1–5 days (bank)",
    regulated: "FinCEN (US), FCA (UK), multiple local regulators",
    features: ["200+ countries & territories", "Cash pickup anywhere", "Agent network", "Mobile & online transfers", "Business solutions"],
    bestFor: ["Remote destinations", "Cash pickup recipients", "Large agent network access"],
  },
];

const PROVIDER_URLS = {
  wise: "https://wise.com",
  remitly: "https://remitly.com",
  "western-union": "https://westernunion.com",
};

const FAQS = [
  { q: "How do I know which provider has the best rate?", a: "Use Vaulto's live comparison tool to see real-time rates from all providers simultaneously. The best rate changes throughout the day." },
  { q: "Are there hidden fees I should know about?", a: "Yes — most providers hide fees inside the exchange rate by marking it up from the mid-market rate. Vaulto shows you the true cost including rate markup + explicit fees." },
  { q: "Which provider is fastest?", a: "Wise offers the fastest bank transfers (often instant to under 2 hours). Remitly is fast for cash pickups. Western Union offers instant cash pickup at agent locations." },
  { q: "Is it safe to use these providers?", a: "All providers listed are regulated by major financial authorities (FCA, FinCEN, ASIC). Your money is protected under their regulatory frameworks." },
];

function FAQItem({ q, a }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="faq-item">
      <button className="faq-q" onClick={() => setOpen(!open)} id={`faq-${q.substring(0,20).replace(/\s/g,"-")}`}>
        {q}
        <span className="faq-chevron">{open ? "−" : "+"}</span>
      </button>
      {open && <div className="faq-a">{a}</div>}
      <style jsx>{`
        .faq-item { border-bottom: 1px solid var(--surface-high); }
        .faq-q {
          width: 100%; display: flex; justify-content: space-between; align-items: center;
          background: none; border: none; padding: 1.25rem 0;
          font-family: var(--font-display); font-weight: 700; font-size: 1rem;
          color: var(--text); cursor: pointer; text-align: left; gap: 1rem;
        }
        .faq-q:hover { color: var(--secondary); }
        .faq-chevron { font-size: 1.2rem; font-weight: 400; flex-shrink: 0; color: var(--secondary); }
        .faq-a { padding-bottom: 1.25rem; font-size: 0.875rem; color: var(--text-mid); line-height: 1.7; }
      `}</style>
    </div>
  );
}

export default function Providers() {
  return (
    <>
      <Head>
        <title>Browse Money Transfer Providers — Vaulto</title>
        <meta name="description" content="Every money transfer provider Vaulto compares — fintechs, brokers, neobanks and banks. Fees, speeds, corridors and transfer limits side by side." />
      </Head>
      <Nav variant="light" />

      {/* Hero */}
      <section className="providers-hero">
        <div className="container">
          <p className="label-sm" style={{ textAlign: "center", marginBottom: "0.75rem" }}>World-class providers</p>
          <h1 className="display-md" style={{ textAlign: "center", marginBottom: "1rem" }}>
            Know your options.<br />Choose with confidence.
          </h1>
          <p style={{ textAlign: "center", color: "var(--muted)", maxWidth: 520, margin: "0 auto 2rem" }}>
            We've vetted the most secure and efficient money transfer services across the globe. Compare fees, speed, and reliability in one unified interface.
          </p>
          <div style={{ textAlign: "center" }}>
            <Link href="/results?from=AUD&to=INR&amount=1000" className="btn-secondary" id="providers-compare-btn">
              Compare live rates →
            </Link>
          </div>
        </div>
      </section>

      {/* Provider cards */}
      <section className="section">
        <div className="container">
          <div className="providers-grid">
            {PROVIDERS.map(p => (
              <div key={p.id} className="prov-card card">
                <div className="prov-accent" style={{ background: p.color }} />
                <div className="prov-header">
                  <div className="prov-icon" style={{ background: `${p.color}18`, color: p.color }}>{p.icon}</div>
                  <div>
                    <div className="prov-name">{p.name}</div>
                    <div className="prov-tagline">{p.tagline}</div>
                  </div>
                </div>
                <p className="prov-desc">{p.description}</p>
                <div className="prov-stats">
                  <div className="prov-stat"><span className="prov-stat-label">Average Fee</span><span className="prov-stat-val">{p.avgFee}</span></div>
                  <div className="prov-stat"><span className="prov-stat-label">Delivery Speed</span><span className="prov-stat-val">{p.speed}</span></div>
                </div>
                <p className="prov-regulated">Regulated by: <strong>{p.regulated}</strong></p>
                <div className="prov-features">
                  {p.features.map(f => (
                    <div key={f} className="prov-feature">
                      <span className="prov-feature-icon">✓</span> {f}
                    </div>
                  ))}
                </div>
                <div className="prov-best">
                  <p className="prov-best-label">Best for</p>
                  {p.bestFor.map(b => <div key={b} className="prov-best-item">★ {b}</div>)}
                </div>
                <div className="prov-actions">
                  <Link href={`/results?from=AUD&to=INR&amount=1000&highlight=${p.id}`} className="btn-secondary" style={{ flex: 1, justifyContent: "center" }} id={`provider-detail-${p.id}`}>
                    Compare {p.name} →
                  </Link>
                  <a href={PROVIDER_URLS[p.id]} target="_blank" rel="noopener noreferrer" className="btn-ghost">Visit site ↗</a>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA dark band */}
      {/* Full registry — the three cards above are the ones we have written
          up in depth; this is everything the engine actually compares. */}
      <section className="providers-all">
        <div className="container">
          <p className="label-sm" style={{ marginBottom: "0.5rem" }}>Every provider we compare</p>
          <h2 className="display-sm" style={{ marginBottom: "0.5rem" }}>
            The full list
          </h2>
          <p style={{ color: "var(--muted)", marginBottom: "2rem", maxWidth: 620 }}>
            Live on every search. Banks are included on purpose — seeing the gap is
            the point.
          </p>
          <ProviderDirectory />
        </div>
      </section>

      <section className="providers-cta">
        <div className="container" style={{ textAlign: "center" }}>
          <h2 className="display-md" style={{ color: "white", marginBottom: "1rem" }}>A Truly Borderless Network</h2>
          <p style={{ color: "rgba(255,255,255,0.65)", marginBottom: "2rem", maxWidth: 480, margin: "0 auto 2rem" }}>
            Vaulto connects you to 200+ countries via 150+ currencies in real time. Find the best provider for your specific needs.
          </p>
          <div style={{ display: "flex", gap: "1rem", justifyContent: "center", flexWrap: "wrap" }}>
            <Link href="/results?from=AUD&to=INR&amount=1000" className="btn-secondary">View Global Map</Link>
            <Link href="/results?from=AUD&to=INR&amount=1000" className="btn-ghost" style={{ color: "rgba(255,255,255,0.8)", borderColor: "rgba(255,255,255,0.25)" }}>Currency Data</Link>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="section">
        <div className="container container-narrow">
          <p className="label-sm" style={{ textAlign: "center", marginBottom: "0.75rem" }}>Common questions</p>
          <h2 className="display-md" style={{ textAlign: "center", marginBottom: "2.5rem" }}>Everything you need to know</h2>
          <div>
            {FAQS.map(f => <FAQItem key={f.q} q={f.q} a={f.a} />)}
          </div>
        </div>
      </section>

      <Footer />

      <style jsx>{`
        .providers-hero { background: var(--surface-low); padding: 5rem 0 3rem; }
        .providers-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.5rem; }
        @media (max-width: 900px) { .providers-grid { grid-template-columns: 1fr; } }

        .prov-card { padding: 0; overflow: hidden; }
        .prov-accent { height: 4px; width: 100%; }
        .prov-header { display: flex; gap: 1rem; align-items: flex-start; padding: 1.5rem 1.5rem 0; margin-bottom: 1rem; }
        .prov-icon { width: 48px; height: 48px; border-radius: var(--radius-md); display: flex; align-items: center; justify-content: center; font-size: 1.4rem; flex-shrink: 0; }
        .prov-name { font-family: var(--font-display); font-weight: 800; font-size: 1.2rem; }
        .prov-tagline { font-size: 0.8rem; color: var(--muted); margin-top: 0.2rem; }
        .prov-desc { padding: 0 1.5rem; font-size: 0.875rem; color: var(--text-mid); line-height: 1.6; margin-bottom: 1rem; }
        .prov-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; padding: 1rem 1.5rem; background: var(--surface-low); margin-bottom: 1rem; }
        .prov-stat { display: flex; flex-direction: column; gap: 0.2rem; }
        .prov-stat-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }
        .prov-stat-val { font-family: var(--font-display); font-weight: 700; font-size: 0.95rem; color: var(--text); }
        .prov-regulated { padding: 0 1.5rem; font-size: 0.75rem; color: var(--muted); margin-bottom: 1rem; }
        .prov-features { padding: 0 1.5rem; display: flex; flex-direction: column; gap: 0.4rem; margin-bottom: 1rem; }
        .prov-feature { font-size: 0.85rem; color: var(--text-mid); display: flex; align-items: center; gap: 0.5rem; }
        .prov-feature-icon { color: var(--secondary); background: var(--secondary-dim); width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.65rem; font-weight: 700; flex-shrink: 0; }
        .prov-best { padding: 0 1.5rem; margin-bottom: 1rem; }
        .prov-best-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); font-weight: 600; margin-bottom: 0.35rem; }
        .prov-best-item { font-size: 0.85rem; color: var(--text-mid); margin-bottom: 0.2rem; }
        .prov-actions { display: flex; gap: 0.75rem; padding: 1rem 1.5rem 1.5rem; }

        .providers-all { padding: 4rem 0; background: var(--surface-low); }

        .providers-cta {
          background: linear-gradient(135deg, var(--primary), #1e3460);
          padding: 5rem 0;
        }
      `}</style>
    </>
  );
}
