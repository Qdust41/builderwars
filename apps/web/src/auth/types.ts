export interface SignedInUser {
  /** Stable id the API uses (Cognito `sub`, or the dev user id). */
  userId: string;
  /** What to show in the header. */
  label: string;
}

/** What the sign-in form should show after a step. */
export type SignInStep =
  | { step: "done" }
  | { step: "confirm-sign-up" } // email not verified yet: ask for the emailed code
  | { step: "new-password" } // account created by an admin with a temporary password
  | { step: "unsupported"; detail: string };

export interface AuthService {
  readonly mode: "dev-header" | "cognito";
  currentUser(): Promise<SignedInUser | null>;
  signIn(email: string, password: string): Promise<SignInStep>;
  completeNewPassword(newPassword: string): Promise<SignInStep>;
  signUp(email: string, password: string): Promise<SignInStep>;
  confirmSignUp(email: string, code: string): Promise<void>;
  resendCode(email: string): Promise<void>;
  signOut(): Promise<void>;
  /** Headers for the platform API. */
  apiHeaders(): Promise<Record<string, string>>;
  /** Headers for AppSync Events (Cognito ID token). */
  realtimeHeaders(): Promise<Record<string, string>>;
}
