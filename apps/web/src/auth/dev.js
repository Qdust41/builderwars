/** LOCAL ONLY: the API trusts `X-Dev-User` when it runs with AUTH_MODE=dev-header. */
export function devHeaderAuth(userId) {
    const unsupported = async () => ({
        step: "unsupported",
        detail: "Sign-in is disabled in local dev mode",
    });
    return {
        mode: "dev-header",
        currentUser: async () => ({ userId, label: `${userId} (local dev)` }),
        signIn: unsupported,
        completeNewPassword: unsupported,
        signUp: unsupported,
        confirmSignUp: async () => undefined,
        resendCode: async () => undefined,
        signOut: async () => undefined,
        apiHeaders: async () => ({ "X-Dev-User": userId }),
        realtimeHeaders: async () => {
            throw new Error("AppSync realtime needs Cognito sign-in (VITE_AUTH_MODE=cognito)");
        },
    };
}
