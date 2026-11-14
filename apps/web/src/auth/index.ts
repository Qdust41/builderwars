import { cognitoAuth } from "./cognito";
import { devHeaderAuth } from "./dev";
import type { AuthService } from "./types";

/** `VITE_AUTH_MODE=cognito` signs in against the user pool; anything else is local dev. */
export function createAuth(): AuthService {
  const env = import.meta.env;
  if (env.VITE_AUTH_MODE === "cognito") {
    if (!env.VITE_COGNITO_USER_POOL_ID || !env.VITE_COGNITO_CLIENT_ID) {
      throw new Error("VITE_AUTH_MODE=cognito needs VITE_COGNITO_USER_POOL_ID and VITE_COGNITO_CLIENT_ID");
    }
    return cognitoAuth({
      userPoolId: env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: env.VITE_COGNITO_CLIENT_ID,
    });
  }
  return devHeaderAuth(env.VITE_DEV_USER ?? "dev-user");
}

export const auth = createAuth();
export type { AuthService, SignedInUser, SignInStep } from "./types";
