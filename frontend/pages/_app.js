import { ClerkProvider } from "@clerk/nextjs";
import "../styles/globals.css";
import "../styles/onboarding.css";

export default function App({ Component, pageProps }) {
  return (
    <ClerkProvider
      // Vaulto owns its sign-in screen, so every redirect Clerk makes on its
      // own — a protected page, an expired session, a sign-out — has to land on
      // /auth. Without these, Clerk falls back to its hosted Account Portal on
      // a different domain, which drops the user out of the product mid-flow.
      signInUrl="/auth"
      signUpUrl="/auth"
      signInFallbackRedirectUrl="/post-auth"
      signUpFallbackRedirectUrl="/post-auth"
      afterSignOutUrl="/"
    >
      <Component {...pageProps} />
    </ClerkProvider>
  );
}
