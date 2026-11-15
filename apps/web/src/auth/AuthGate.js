import { jsx as _jsx } from "react/jsx-runtime";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../api/client";
import { auth as defaultAuth } from ".";
import { Spinner } from "../components/ui";
import { SignInPage } from "./SignInPage";
const SessionContext = createContext(null);
export function useSession() {
    return useContext(SessionContext);
}
/** Renders `children` once someone is signed in; otherwise the sign-in page. */
export function AuthGate({ children, auth = defaultAuth }) {
    const [user, setUser] = useState();
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
    if (user === undefined)
        return _jsx(Spinner, {});
    if (user === null)
        return _jsx(SignInPage, { auth: auth, onSignedIn: refresh });
    const session = {
        user,
        mode: auth.mode,
        signOut: async () => {
            await auth.signOut();
            setUser(null);
        },
    };
    return _jsx(SessionContext.Provider, { value: session, children: children });
}
