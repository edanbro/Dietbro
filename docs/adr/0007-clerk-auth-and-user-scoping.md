# ADR-0007: Clerk for sign-in; the API verifies JWTs and scopes every query by user

- Status: Accepted
- Date: 2026-10-08

## Context

M2 adds accounts. PLAN §3 says "don't hand-roll auth". Options:

1. **Clerk.** Hosted sign-up/sign-in UI and sessions; free up to 10k monthly users; first-class
   Next.js SDK; session tokens are short-lived RS256 JWTs verifiable via a public JWKS.
2. **Auth0.** Same JWT/JWKS model; more configuration, smaller free tier.
3. **Self-hosted (Better Auth / Auth.js).** No third party and data stays in our Postgres, but we
   own password storage, email verification and delivery, and abuse protection.

## Decision

Clerk, with the API as an independent verifier:

- The web app gets a session token from Clerk (`useAuth().getToken()`) and sends it as
  `Authorization: Bearer`. The API checks the RS256 signature against the instance JWKS (cached;
  refetched hourly or on an unknown `kid`, rate-limited), `iss`, `exp`/`nbf` (5 s leeway) and
  `azp` (the origin the token was minted for). No calls to Clerk per request.
- The JWT `sub` (Clerk user id) maps to a local `users` row, created on first use. Every user
  table is keyed by or filtered on `users.id`; routers fetch rows with `user_id = current user`,
  so another user's id is a 404, never a 403 that confirms existence.
- The Next.js proxy (`clerkMiddleware`) redirects signed-out visitors away from app pages. It
  is a UX convenience; the API is the security boundary.
- The issuer is derived from the publishable key, so configuration is two keys in `.env`.
- Account deletion deletes our rows (cascade) and the Clerk user (client SDK). Export returns
  every row we hold for the user.

## Consequences

- Sign-up, password reset, email verification and bot protection are Clerk's; we never see
  passwords. A Clerk outage blocks sign-in (existing sessions keep working until expiry).
- Local and CI runs need Clerk keys. Unit/API tests mint tokens with a local RSA key against a
  static JWKS; the Playwright e2e uses a Clerk dev instance via `@clerk/testing` and skips
  without keys. The Docker smoke test boots with placeholder keys.
- Swapping providers later means replacing the web SDK and the issuer/JWKS settings; the API's
  `users.auth_subject` mapping stays.
