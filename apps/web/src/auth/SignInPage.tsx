import { useState, type FormEvent } from "react";
import type { AuthService, SignInStep } from "./types";

type View = "sign-in" | "sign-up" | "confirm" | "new-password";

const TITLES: Record<View, string> = {
  "sign-in": "Sign in",
  "sign-up": "Create an account",
  confirm: "Check your email",
  "new-password": "Choose a new password",
};

export function SignInPage({ auth, onSignedIn }: { auth: AuthService; onSignedIn: () => void }) {
  const [view, setView] = useState<View>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(undefined);
    setNotice(undefined);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function follow(step: SignInStep) {
    if (step.step === "done") onSignedIn();
    else if (step.step === "confirm-sign-up") setView("confirm");
    else if (step.step === "new-password") {
      setPassword("");
      setView("new-password");
    } else setError(step.detail);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      if (view === "sign-in") follow(await auth.signIn(email, password));
      else if (view === "sign-up") follow(await auth.signUp(email, password));
      else if (view === "new-password") follow(await auth.completeNewPassword(password));
      else {
        await auth.confirmSignUp(email, code);
        // Confirmed: sign straight in with the password they just chose, if we still have it.
        if (password) follow(await auth.signIn(email, password));
        else {
          setView("sign-in");
          setNotice("Email confirmed. Sign in to continue.");
        }
      }
    });
  }

  return (
    <div className="signin">
      <form className="signin-card" onSubmit={submit}>
        <h1>{TITLES[view]}</h1>
        {view === "confirm" && (
          <p className="muted">We sent a verification code to {email || "your email"}.</p>
        )}
        {view !== "new-password" && (
          <label>
            Email
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
        )}
        {view === "confirm" ? (
          <label>
            Verification code
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
        ) : (
          <label>
            {view === "new-password" ? "New password" : "Password"}
            <input
              type="password"
              autoComplete={view === "sign-in" ? "current-password" : "new-password"}
              required
              minLength={view === "sign-in" ? undefined : 8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
        )}
        {view !== "sign-in" && view !== "confirm" && (
          <p className="muted small">At least 8 characters, with upper and lower case letters and a digit.</p>
        )}
        {error && <p className="error">{error}</p>}
        {notice && <p className="muted">{notice}</p>}
        <button type="submit" disabled={busy}>
          {view === "sign-in" ? "Sign in" : view === "sign-up" ? "Create account" : view === "confirm" ? "Confirm" : "Save password"}
        </button>
        <div className="signin-links">
          {view === "sign-in" && (
            <button type="button" className="link" onClick={() => setView("sign-up")}>
              Create an account
            </button>
          )}
          {view === "sign-up" && (
            <button type="button" className="link" onClick={() => setView("sign-in")}>
              I already have an account
            </button>
          )}
          {view === "confirm" && (
            <button
              type="button"
              className="link"
              disabled={busy || !email}
              onClick={() =>
                void run(async () => {
                  await auth.resendCode(email);
                  setNotice("A new code is on its way.");
                })
              }
            >
              Send a new code
            </button>
          )}
        </div>
        {view === "sign-up" && (
          <p className="muted small">
            A new account sees no projects until a project owner or admin adds your email.
          </p>
        )}
      </form>
    </div>
  );
}
