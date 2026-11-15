import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { auth as defaultAuth } from ".";
import { SignInPage } from "./SignInPage";
import type { AuthService, SignedInUser } from "./types";

interface Session {
  user: SignedInUser;
  mode: AuthService["mode"];
  signOut: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session | null {
  return useContext(SessionContext);
}

/** Renders `children` once someone is signed in; otherwise the sign-in page. */
export function AuthGate({ children, auth = defaultAuth }: { children: ReactNode; auth?: AuthService }) {
  const [user, setUser] = useState<SignedInUser | null>();

  const refresh = useCallback(() => {
    auth.currentUser().then(setUser, () => setUser(null));
  }, [auth]);

  useEffect(() => {
    refresh();
    // An expired or revoked session shows up as a 401 from the API.
    api.onUnauthorized = auth.mode === "cognito" ? refresh : undefined;
    return () => {
      api.onUnauthorized = undefined;
    };
  }, [auth, refresh]);

  if (user === undefined) return <p className="muted center">Loading…</p>;
  if (user === null) return <SignInPage auth={auth} onSignedIn={refresh} />;
  const session: Session = {
    user,
    mode: auth.mode,
    signOut: async () => {
      await auth.signOut();
      setUser(null);
    },
  };
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}
