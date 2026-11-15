import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { Check } from "lucide-react";
import { useState } from "react";
import { ErrorBanner, Logo } from "../components/ui";
const TITLES = {
    "sign-in": "Sign in",
    "sign-up": "Create an account",
    confirm: "Check your email",
    "new-password": "Choose a new password",
};
export function SignInPage({ auth, onSignedIn }) {
    const [view, setView] = useState("sign-in");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [code, setCode] = useState("");
    const [error, setError] = useState();
    const [notice, setNotice] = useState();
    const [busy, setBusy] = useState(false);
    async function run(action) {
        setBusy(true);
        setError(undefined);
        setNotice(undefined);
        try {
            await action();
        }
        catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
        finally {
            setBusy(false);
        }
    }
    function follow(step) {
        if (step.step === "done")
            onSignedIn();
        else if (step.step === "confirm-sign-up")
            setView("confirm");
        else if (step.step === "new-password") {
            setPassword("");
            setView("new-password");
        }
        else
            setError(step.detail);
    }
    function submit(e) {
        e.preventDefault();
        void run(async () => {
            if (view === "sign-in")
                follow(await auth.signIn(email, password));
            else if (view === "sign-up")
                follow(await auth.signUp(email, password));
            else if (view === "new-password")
                follow(await auth.completeNewPassword(password));
            else {
                await auth.confirmSignUp(email, code);
                // Confirmed: sign straight in with the password they just chose, if we still have it.
                if (password)
                    follow(await auth.signIn(email, password));
                else {
                    setView("sign-in");
                    setNotice("Email confirmed. Sign in to continue.");
                }
            }
        });
    }
    const field = "input mt-1.5";
    return (_jsxs("div", { className: "flex min-h-screen bg-bg", children: [_jsxs("aside", { className: "relative hidden w-[44%] overflow-hidden bg-zinc-950 p-10 text-zinc-100 lg:flex lg:flex-col", children: [_jsx("div", { "aria-hidden": "true", className: "absolute inset-0 opacity-[0.15]", style: {
                            backgroundImage: "linear-gradient(to right, #a5b4fc 1px, transparent 1px), linear-gradient(to bottom, #a5b4fc 1px, transparent 1px)",
                            backgroundSize: "32px 32px",
                            maskImage: "radial-gradient(ellipse at 30% 40%, black 20%, transparent 70%)",
                        } }), _jsx("div", { "aria-hidden": "true", className: "absolute -top-24 -left-24 size-96 rounded-full bg-indigo-600/30 blur-3xl" }), _jsx(Logo, { className: "relative text-white" }), _jsxs("div", { className: "relative mt-auto max-w-md", children: [_jsx("h2", { className: "text-3xl font-semibold tracking-tight text-white", children: "Build hardware together, from anywhere." }), _jsx("p", { className: "mt-3 text-zinc-400", children: "Register your boards, stream their telemetry and logs, and send commands from one shared dashboard." }), _jsx("ul", { className: "mt-8 space-y-3 text-sm text-zinc-300", children: ["Live charts for every reading", "Logs and command results as they happen", "Projects shared with your team"].map((t) => (_jsxs("li", { className: "flex items-center gap-3", children: [_jsx("span", { className: "grid size-5 place-items-center rounded-full bg-indigo-500/20 text-indigo-300", children: _jsx(Check, { className: "size-3", "aria-hidden": "true" }) }), t] }, t))) })] })] }), _jsx("main", { className: "flex flex-1 items-center justify-center px-4 py-12", children: _jsxs("form", { className: "w-full max-w-sm", onSubmit: submit, children: [_jsx(Logo, { className: "mb-10 text-fg lg:hidden" }), _jsx("h1", { className: "text-2xl font-semibold tracking-tight text-fg", children: TITLES[view] }), _jsx("p", { className: "mt-1.5 text-sm text-muted", children: view === "sign-in"
                                ? "Welcome back. Sign in with your email and password."
                                : view === "sign-up"
                                    ? "Create an account, then start your own project."
                                    : view === "confirm"
                                        ? `We sent a verification code to ${email || "your email"}.`
                                        : "Your account needs a new password before you continue." }), _jsxs("div", { className: "mt-8 space-y-4", children: [view !== "new-password" && (_jsxs("label", { className: "block text-sm font-medium text-fg-2", children: ["Email", _jsx("input", { className: field, type: "email", autoComplete: "username", required: true, value: email, onChange: (e) => setEmail(e.target.value), placeholder: "you@example.com" })] })), view === "confirm" ? (_jsxs("label", { className: "block text-sm font-medium text-fg-2", children: ["Verification code", _jsx("input", { className: `${field} font-mono tracking-[0.3em]`, inputMode: "numeric", autoComplete: "one-time-code", required: true, value: code, onChange: (e) => setCode(e.target.value) })] })) : (_jsxs("label", { className: "block text-sm font-medium text-fg-2", children: [view === "new-password" ? "New password" : "Password", _jsx("input", { className: field, type: "password", autoComplete: view === "sign-in" ? "current-password" : "new-password", required: true, minLength: view === "sign-in" ? undefined : 8, value: password, onChange: (e) => setPassword(e.target.value) }), view !== "sign-in" && (_jsx("span", { className: "mt-1.5 block text-xs font-normal text-muted", children: "At least 8 characters, with upper and lower case letters and a digit." }))] }))] }), error && (_jsx("div", { className: "mt-4", children: _jsx(ErrorBanner, { children: error }) })), notice && (_jsx("p", { className: "mt-4 rounded-lg bg-good-soft px-3.5 py-2.5 text-sm text-good", role: "status", children: notice })), _jsx("button", { type: "submit", disabled: busy, className: "btn-primary mt-6 w-full py-2.5", children: busy
                                ? "Please wait…"
                                : view === "sign-in"
                                    ? "Sign in"
                                    : view === "sign-up"
                                        ? "Create account"
                                        : view === "confirm"
                                            ? "Confirm"
                                            : "Save password" }), _jsxs("p", { className: "mt-6 text-center text-sm text-muted", children: [view === "sign-in" && (_jsxs(_Fragment, { children: ["New here?", " ", _jsx("button", { type: "button", className: "font-medium text-accent hover:underline", onClick: () => setView("sign-up"), children: "Create an account" })] })), view === "sign-up" && (_jsxs(_Fragment, { children: ["Already have an account?", " ", _jsx("button", { type: "button", className: "font-medium text-accent hover:underline", onClick: () => setView("sign-in"), children: "Sign in" })] })), view === "confirm" && (_jsxs(_Fragment, { children: ["Didn't get it?", " ", _jsx("button", { type: "button", className: "font-medium text-accent hover:underline disabled:opacity-50", disabled: busy || !email, onClick: () => void run(async () => {
                                                await auth.resendCode(email);
                                                setNotice("A new code is on its way.");
                                            }), children: "Send a new code" })] }))] })] }) })] }));
}
