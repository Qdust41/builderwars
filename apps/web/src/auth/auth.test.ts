import { beforeEach, describe, expect, it, vi } from "vitest";

const amplify = vi.hoisted(() => ({
  configure: vi.fn(),
  signIn: vi.fn(),
  confirmSignIn: vi.fn(),
  signUp: vi.fn(),
  confirmSignUp: vi.fn(),
  resendSignUpCode: vi.fn(),
  signOut: vi.fn(),
  getCurrentUser: vi.fn(),
  fetchAuthSession: vi.fn(),
}));

vi.mock("aws-amplify", () => ({ Amplify: { configure: amplify.configure } }));
vi.mock("aws-amplify/auth", () => amplify);

import { cognitoAuth } from "./cognito";
import { devHeaderAuth } from "./dev";

const token = (value: string, payload: Record<string, unknown> = {}) => ({
  toString: () => value,
  payload,
});

beforeEach(() => vi.clearAllMocks());

describe("devHeaderAuth", () => {
  it("sends the dev user header and refuses AppSync", async () => {
    const a = devHeaderAuth("alice");
    expect(await a.apiHeaders()).toEqual({ "X-Dev-User": "alice" });
    expect((await a.currentUser())?.userId).toBe("alice");
    await expect(a.realtimeHeaders()).rejects.toThrow(/Cognito/);
  });
});

describe("cognitoAuth", () => {
  const config = { userPoolId: "us-east-1_abc", userPoolClientId: "client123" };

  it("configures the pool for email sign-in", () => {
    cognitoAuth(config);
    expect(amplify.configure).toHaveBeenCalledWith({
      Auth: {
        Cognito: {
          userPoolId: "us-east-1_abc",
          userPoolClientId: "client123",
          loginWith: { email: true },
          signUpVerificationMethod: "code",
        },
      },
    });
  });

  it("gives the API the access token and AppSync the ID token", async () => {
    amplify.fetchAuthSession.mockResolvedValue({
      tokens: { accessToken: token("acc"), idToken: token("id", { email: "a@x.io" }) },
    });
    amplify.getCurrentUser.mockResolvedValue({ userId: "sub-1", username: "sub-1" });
    const a = cognitoAuth(config);
    expect(await a.apiHeaders()).toEqual({ Authorization: "Bearer acc" });
    expect(await a.realtimeHeaders()).toEqual({ Authorization: "id" });
    expect(await a.currentUser()).toEqual({ userId: "sub-1", label: "a@x.io" });
  });

  it("is signed out when there is no session", async () => {
    amplify.getCurrentUser.mockRejectedValue(new Error("UserUnAuthenticatedException"));
    amplify.fetchAuthSession.mockResolvedValue({ tokens: undefined });
    const a = cognitoAuth(config);
    expect(await a.currentUser()).toBeNull();
    await expect(a.apiHeaders()).rejects.toThrow("not signed in");
  });

  it("maps sign-in and sign-up steps", async () => {
    const a = cognitoAuth(config);
    amplify.signIn.mockResolvedValueOnce({ nextStep: { signInStep: "DONE" } });
    expect(await a.signIn(" a@x.io ", "pw")).toEqual({ step: "done" });
    expect(amplify.signIn).toHaveBeenCalledWith({ username: "a@x.io", password: "pw" });

    amplify.signIn.mockResolvedValueOnce({ nextStep: { signInStep: "CONFIRM_SIGN_UP" } });
    expect(await a.signIn("a@x.io", "pw")).toEqual({ step: "confirm-sign-up" });

    amplify.signIn.mockResolvedValueOnce({
      nextStep: { signInStep: "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED" },
    });
    expect(await a.signIn("a@x.io", "temp")).toEqual({ step: "new-password" });

    amplify.signIn.mockResolvedValueOnce({ nextStep: { signInStep: "CONFIRM_SIGN_IN_WITH_TOTP_CODE" } });
    expect((await a.signIn("a@x.io", "pw")).step).toBe("unsupported");

    amplify.signUp.mockResolvedValueOnce({ nextStep: { signUpStep: "CONFIRM_SIGN_UP" } });
    expect(await a.signUp("a@x.io", "Passw0rd")).toEqual({ step: "confirm-sign-up" });
    expect(amplify.signUp).toHaveBeenCalledWith({
      username: "a@x.io",
      password: "Passw0rd",
      options: { userAttributes: { email: "a@x.io" } },
    });
  });
});
