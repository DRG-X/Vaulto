import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import { useAuth, useUser } from "../contexts/AuthContext";

/**
 * Nav — Reusable navigation bar.
 * Props:
 *   variant  "light" | "dark"   — light uses white/glass bg; dark uses navy/glass
 *   showDashboardLink  boolean  — show Dashboard link (authenticated users)
 */
export default function Nav({ variant = "light", showDashboardLink = false }) {
  const router = useRouter();
  const { isSignedIn, signOut } = useAuth();
  const { user } = useUser();
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const handleSignOut = async () => {
    await signOut();
    router.push("/");
  };

  const initials = user?.initials || "?";

  const navLinks = [
    { href: "/results?from=AUD&to=INR&amount=1000", label: "Compare" },
    { href: "/providers", label: "Providers" },
    { href: "/insights", label: "Insights" },
    { href: "/about", label: "About" },
  ];

  return (
    <>
      <nav className={`nav ${variant === "dark" ? "nav-dark" : ""} ${scrolled ? "scrolled" : ""}`}>
        <div className="container">
          <div className="nav-inner">
            {/* Logo */}
            <Link href="/" className="logo" id="nav-logo">
              <span className="logo-mark">V</span>
              <span>Vaulto</span>
            </Link>

            {/* Desktop Links */}
            <div className="nav-links desktop-only">
              {navLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`nav-link ${router.pathname === link.href.split("?")[0] ? "active" : ""}`}
                >
                  {link.label}
                </Link>
              ))}
              {(isSignedIn || showDashboardLink) && (
                <Link
                  href="/dashboard"
                  className={`nav-link ${router.pathname === "/dashboard" ? "active" : ""}`}
                >
                  Dashboard
                </Link>
              )}
            </div>

            {/* Right Actions */}
            <div className="nav-actions desktop-only">
              {isSignedIn ? (
                <div className="nav-user">
                  <div className="nav-avatar" title={user?.fullName || ""}>{initials}</div>
                  <button className="btn-ghost" onClick={handleSignOut} id="nav-logout">
                    Log out
                  </button>
                </div>
              ) : (
                <>
                  <Link href="/auth" className="btn-ghost" id="nav-login">Log in</Link>
                  <Link href="/auth?mode=signup" className="btn-secondary" id="nav-signup">
                    Get started →
                  </Link>
                </>
              )}
            </div>

            {/* Mobile Hamburger */}
            <button
              className="hamburger"
              onClick={() => setMenuOpen(!menuOpen)}
              aria-label="Toggle menu"
              id="nav-hamburger"
            >
              <span className={`ham-line ${menuOpen ? "open" : ""}`} />
              <span className={`ham-line ${menuOpen ? "open" : ""}`} />
              <span className={`ham-line ${menuOpen ? "open" : ""}`} />
            </button>
          </div>
        </div>

        {/* Mobile Menu */}
        {menuOpen && (
          <div className="mobile-menu">
            <div className="container">
              {navLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="mobile-link"
                  onClick={() => setMenuOpen(false)}
                >
                  {link.label}
                </Link>
              ))}
              {(isSignedIn || showDashboardLink) && (
                <Link href="/dashboard" className="mobile-link" onClick={() => setMenuOpen(false)}>
                  Dashboard
                </Link>
              )}
              <div className="mobile-actions">
                {isSignedIn ? (
                  <button className="btn-ghost" onClick={handleSignOut} style={{ width: "100%" }}>
                    Log out
                  </button>
                ) : (
                  <>
                    <Link href="/auth" className="btn-ghost" style={{ width: "100%", justifyContent: "center" }} onClick={() => setMenuOpen(false)}>
                      Log in
                    </Link>
                    <Link href="/auth?mode=signup" className="btn-secondary" style={{ width: "100%", justifyContent: "center" }} onClick={() => setMenuOpen(false)}>
                      Get started →
                    </Link>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </nav>

      <style jsx>{`
        .nav-dark {
          background: rgba(11, 18, 32, 0.85) !important;
        }
        .nav-dark .nav-link { color: rgba(255,255,255,0.7); }
        .nav-dark .nav-link:hover { color: white; background: rgba(255,255,255,0.08); }
        .nav-dark .nav-link.active { color: white; background: rgba(255,255,255,0.12); }
        .nav-dark .logo { color: white; }
        .nav-dark.scrolled { box-shadow: 0 1px 0 rgba(255,255,255,0.05); }

        .nav-actions { display: flex; align-items: center; gap: 0.5rem; }

        .nav-user { display: flex; align-items: center; gap: 0.75rem; }
        .nav-avatar {
          width: 32px; height: 32px;
          background: linear-gradient(135deg, var(--secondary), var(--tertiary));
          border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          font-size: 0.75rem; font-weight: 700; color: white;
          font-family: var(--font-display);
          flex-shrink: 0;
        }

        .hamburger {
          display: none;
          flex-direction: column; gap: 5px;
          background: none; border: none; cursor: pointer; padding: 4px;
        }
        .ham-line {
          display: block; width: 22px; height: 2px;
          background: var(--text); border-radius: 2px;
          transition: transform 0.2s, opacity 0.2s;
        }
        .nav-dark .ham-line { background: white; }
        .ham-line.open:nth-child(1) { transform: rotate(45deg) translate(5px, 5px); }
        .ham-line.open:nth-child(2) { opacity: 0; }
        .ham-line.open:nth-child(3) { transform: rotate(-45deg) translate(5px, -5px); }

        .mobile-menu {
          background: var(--surface-float);
          border-top: 1px solid var(--surface-high);
          padding: 1rem 0 1.5rem;
          box-shadow: var(--shadow-md);
        }
        .nav-dark + .mobile-menu,
        .nav-dark .mobile-menu {
          background: var(--primary);
          border-top-color: rgba(255,255,255,0.08);
        }
        .mobile-link {
          display: block;
          padding: 0.75rem 0;
          font-family: var(--font-body);
          font-size: 1rem;
          font-weight: 500;
          color: var(--text-mid);
          text-decoration: none;
          border-bottom: 1px solid var(--surface-high);
        }
        .mobile-link:hover { color: var(--text); }
        .mobile-actions {
          display: flex; flex-direction: column; gap: 0.75rem;
          padding-top: 1rem;
        }

        @media (max-width: 768px) {
          .hamburger { display: flex; }
          .desktop-only { display: none !important; }
        }
      `}</style>
    </>
  );
}
