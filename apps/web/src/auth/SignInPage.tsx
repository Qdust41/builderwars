import { Check } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBanner, Logo } from "../components/ui";
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

  const field = "input mt-1.5";
  return (
    <div className="flex min-h-screen bg-bg">
      <aside className="relative hidden w-[44%] overflow-hidden bg-zinc-950 p-10 text-zinc-100 lg:flex lg:flex-col">
        <div
          aria-hidden="true"
          className="absolute inset-0 opacity-[0.15]"
          style={{
            backgroundImage:
              "linear-gradient(to right, #a5b4fc 1px, transparent 1px), linear-gradient(to bottom, #a5b4fc 1px, transparent 1px)",
            backgroundSize: "32px 32px",
            maskImage: "radial-gradient(ellipse at 30% 40%, black 20%, transparent 70%)",
          }}
        />
        <div aria-hidden="true" className="absolute -top-24 -left-24 size-96 rounded-full bg-indigo-600/30 blur-3xl" />
        <Logo className="relative text-white" />
        <div className="relative mt-auto max-w-md">
          <h2 className="text-3xl font-semibold tracking-tight text-white">
            Build hardware together, from anywhere.
          </h2>
          <p className="mt-3 text-zinc-400">
            Register your boards, stream their telemetry and logs, and send commands from one shared dashboard.
          </p>
          <ul className="mt-8 space-y-3 text-sm text-zinc-300">
            {["Live charts for every reading", "Logs and command results as they happen", "Projects shared with your team"].map(
              (t) => (
                <li key={t} className="flex items-center gap-3">
                  <span className="grid size-5 place-items-center rounded-full bg-indigo-500/20 text-indigo-300">
                    <Check className="size-3" aria-hidden="true" />
                  </span>
                  {t}
                </li>
              ),
            )}
          </ul>
        </div>
      </aside>

      <main className="flex flex-1 items-center justify-center px-4 py-12">
        <form className="w-full max-w-sm" onSubmit={submit}>
          <Logo className="mb-10 text-fg lg:hidden" />
          <h1 className="text-2xl font-semibold tracking-tight text-fg">{TITLES[view]}</h1>
          <p className="mt-1.5 text-sm text-muted">
            {view === "sign-in"
              ? "Welcome back. Sign in with your email and password."
              : view === "sign-up"
                ? "Create an account, then start your own project."
                : view === "confirm"
                  ? `We sent a verification code to ${email || "your email"}.`
                  : "Your account needs a new password before you continue."}
          </p>

          <div className="mt-8 space-y-4">
            {view !== "new-password" && (
              <label className="block text-sm font-medium text-fg-2">
                Email
                <input
                  className={field}
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                />
              </label>
            )}
            {view === "confirm" ? (
              <label className="block text-sm font-medium text-fg-2">
                Verification code
                <input
                  className={`${field} font-mono tracking-[0.3em]`}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </label>
            ) : (
              <label className="block text-sm font-medium text-fg-2">
                {view === "new-password" ? "New password" : "Password"}
                <input
                  className={field}
                  type="password"
                  autoComplete={view === "sign-in" ? "current-password" : "new-password"}
                  required
                  minLength={view === "sign-in" ? undefined : 8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                {view !== "sign-in" && (
                  <span className="mt-1.5 block text-xs font-normal text-muted">
                    At least 8 characters, with upper and lower case letters and a digit.
                  </span>
                )}
              </label>
            )}
          </div>

          {error && (
            <div className="mt-4">
              <ErrorBanner>{error}</ErrorBanner>
            </div>
          )}
          {notice && (
            <p className="mt-4 rounded-lg bg-good-soft px-3.5 py-2.5 text-sm text-good" role="status">
              {notice}
            </p>
          )}

          <button type="submit" disabled={busy} className="btn-primary mt-6 w-full py-2.5">
            {busy
              ? "Please wait…"
              : view === "sign-in"
                ? "Sign in"
                : view === "sign-up"
                  ? "Create account"
                  : view === "confirm"
                    ? "Confirm"
                    : "Save password"}
          </button>

          <p className="mt-6 text-center text-sm text-muted">
            {view === "sign-in" && (
              <>
                New here?{" "}
                <button type="button" className="font-medium text-accent hover:underline" onClick={() => setView("sign-up")}>
                  Create an account
                </button>
              </>
            )}
            {view === "sign-up" && (
              <>
                Already have an account?{" "}
                <button type="button" className="font-medium text-accent hover:underline" onClick={() => setView("sign-in")}>
                  Sign in
                </button>
              </>
            )}
            {view === "confirm" && (
              <>
                Didn't get it?{" "}
                <button
                  type="button"
                  className="font-medium text-accent hover:underline disabled:opacity-50"
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
              </>
            )}
          </p>
        </form>
      </main>
    </div>
  );
}
