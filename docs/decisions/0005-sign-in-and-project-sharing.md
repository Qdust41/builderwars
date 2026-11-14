# 0005 — Sign-in and project sharing

Status: accepted (2026-11-14, decision #10 confirmed by the owner)

## Context
The API needs real authentication outside local/test, and projects need a way to be shared.
Decision #10 recommended per-project roles with owner-managed membership; the owner confirmed
it and chose the simplest sign-in for the MVP.

## Decision
- **Sign-in:** Cognito user pool, email + password only (no social or federated providers).
  Self sign-up is **on**, with an emailed verification code. MFA is **off** for the MVP.
- **Tokens:** the API verifies every bearer token itself (RS256 signature against the pool's
  JWKS, issuer, expiry, and the app client via `client_id` on access tokens or `aud` on ID
  tokens), in addition to API Gateway's JWT authorizer. The user id is the Cognito `sub`.
- **Sharing:** per-project roles owner / admin / member / viewer. Owners and admins add
  existing accounts by email (`POST /projects/{id}/members`); only the owner grants or removes
  admins; ownership is never granted this way; anyone except the owner can leave. No invite
  links, no orgs.
- **Errors:** missing or bad token → 401; member lacking a permission → 403; non-member →
  404 (so ids can't be probed); unknown email → 404; already a member → 409.

## Consequences
- Anyone can create an account, but a new account sees nothing until someone adds it to a
  project. The person being added must have signed up first.
- Email lookups go to Cognito `ListUsers` (`cognito-idp:ListUsers` on the pool only).
- Cognito's default email sender is limited to about 50 emails a day; move to SES before
  inviting real users.
- MFA, social sign-in, role changes and ownership transfer are follow-ups.
