import { AuthProvider } from "../contexts/AuthContext";
import "../styles/globals.css";
import "../styles/onboarding.css";

export default function App({ Component, pageProps }) {
  return (
    <AuthProvider>
      <Component {...pageProps} />
    </AuthProvider>
  );
}
