import { Amplify } from "aws-amplify";
import { confirmSignIn, confirmSignUp, fetchAuthSession, getCurrentUser, resendSignUpCode, signIn, signOut, signUp, } from "aws-amplify/auth";
/**
 * Cognito user pool sign-in (email + password, SRP), self sign-up with an emailed code.
 * Matches the pool in infrastructure/stacks/identity.py. Tokens live in Amplify's store
 * (localStorage) and refresh automatically; the API gets the access token, AppSync the ID
 * token.
 */
export function cognitoAuth(config) {
    Amplify.configure({
        Auth: {
            Cognito: {
                userPoolId: config.userPoolId,
                userPoolClientId: config.userPoolClientId,
                loginWith: { email: true },
                signUpVerificationMethod: "code",
            },
        },
    });
    const tokens = async () => {
        const session = await fetchAuthSession();
        if (!session.tokens?.accessToken)
            throw new Error("not signed in");
        return session.tokens;
    };
    return {
        mode: "cognito",
        async currentUser() {
            try {
                const user = await getCurrentUser();
                const t = await tokens();
                const email = t.idToken?.payload.email;
                return { userId: user.userId, label: typeof email === "string" ? email : user.username };
            }
            catch {
                return null;
            }
        },
        async signIn(email, password) {
            return toStep(await signIn({ username: email.trim(), password }));
        },
        async completeNewPassword(newPassword) {
            return toStep(await confirmSignIn({ challengeResponse: newPassword }));
        },
        async signUp(email, password) {
            const result = await signUp({
                username: email.trim(),
                password,
                options: { userAttributes: { email: email.trim() } },
            });
            return result.nextStep.signUpStep === "CONFIRM_SIGN_UP"
                ? { step: "confirm-sign-up" }
                : { step: "done" };
        },
        async confirmSignUp(email, code) {
            await confirmSignUp({ username: email.trim(), confirmationCode: code.trim() });
        },
        async resendCode(email) {
            await resendSignUpCode({ username: email.trim() });
        },
        async signOut() {
            await signOut();
        },
        async apiHeaders() {
            return { Authorization: `Bearer ${(await tokens()).accessToken.toString()}` };
        },
        async realtimeHeaders() {
            const id = (await tokens()).idToken;
            if (!id)
                throw new Error("no ID token in the session");
            return { Authorization: id.toString() };
        },
    };
}
function toStep(output) {
    switch (output.nextStep.signInStep) {
        case "DONE":
            return { step: "done" };
        case "CONFIRM_SIGN_UP":
            return { step: "confirm-sign-up" };
        case "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED":
            return { step: "new-password" };
        default:
            return { step: "unsupported", detail: `Unsupported sign-in step: ${output.nextStep.signInStep}` };
    }
}
