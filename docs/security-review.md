# Security review before hosting

Reviewed on 2026-11-01, before the first public deploy. The roadmap asked for the share and
calendar tokens, the recipe-import SSRF guard and the rate limits. Most of what needed fixing turned
out to be next to those, not in them.

The method: read the code, then test what looked wrong instead of arguing about it. Timings and
reads below were measured. This was a code review by the project's own main coder, not an external
penetration test, and nothing here was run against a hosted copy.

## Found and fixed

| Severity | Finding | Evidence | Fix |
|---|---|---|---|
| Critical | `next` 16.4.0 had two advisories for unauthenticated remote code execution | `pnpm audit --prod` | 16.4.3 ([#90](https://github.com/edanbro/Dietbro/pull/90)) |
| High | One hostile recipe page froze the whole API: a quadratic regex on the event loop | 154 s at 500 KB, so about 40 minutes at the 2 MB limit | A forward-only scan in a worker thread ([#91](https://github.com/edanbro/Dietbro/pull/91)) |
| High | A body of any size was read before sign-in was checked | 50 MB read with no token | A 9 MB limit, refused unread where declared ([#92](https://github.com/edanbro/Dietbro/pull/92)) |
| High | Pillow 12.3.0, which decodes uploaded photos, had 39 advisories | `pip-audit` | 13.0.0 ([#90](https://github.com/edanbro/Dietbro/pull/90)) |
| Medium | Any `https://` address was accepted as a push endpoint, and the server POSTs to it | Read the code | Real browser push services only ([#91](https://github.com/edanbro/Dietbro/pull/91)) |
| Medium | Rate limits turned off when Redis failed, and a bot could use up the free plan's commands in hours | Arithmetic on Upstash's 500K a month | Public routes count in the process, the rest fall back to it ([#92](https://github.com/edanbro/Dietbro/pull/92)) |
| Medium | Any visitor could publish a share link, a calendar feed or reminders from the shared demo account | Read the code | Refused for that account ([#93](https://github.com/edanbro/Dietbro/pull/93)) |
| Medium | A visitor could delete the demo user through Clerk, past our API | Read the code | Turned off per user by `/api/demo` ([#93](https://github.com/edanbro/Dietbro/pull/93)) |
| Medium | The demo reset needed the host awake at exactly 03:00 | Read the code | Goes by the row's age and catches up on waking ([#93](https://github.com/edanbro/Dietbro/pull/93)) |
| Low | `::127.0.0.1` and `fec0::1` counted as public addresses | `ipaddress.is_global` says so | Refused ([#91](https://github.com/edanbro/Dietbro/pull/91)) |
| Low | Malformed addresses and deeply nested JSON gave a 500 | Tried them | The normal refusal ([#91](https://github.com/edanbro/Dietbro/pull/91)) |
| Low | Share and calendar tokens appeared in access logs | Read the code | Masked ([#92](https://github.com/edanbro/Dietbro/pull/92)) |
| Low | 3 request fields had no size limit | Walked every request schema in OpenAPI | Capped ([#92](https://github.com/edanbro/Dietbro/pull/92)) |

Nothing watched for new advisories, which is how the first row got this far.
`.github/workflows/audit.yml` now checks what ships every week.

## Reviewed and sound

- **Share and calendar tokens.** 128 random bits from `secrets`, so they can't be guessed. Revocable
  or resettable, `noindex`, and share pages leave out pantry, goals, weight, allergies and name.
- **The SSRF guard's design.** Every address a name resolves to is checked, and the connection goes
  to the checked address, so DNS rebinding fails. Redirects are checked again. Size is counted as
  it decompresses, and time is capped.
- **Sign-in.** RS256 only, with issuer and expiry checked. The API verifies every request itself, so
  the web app's redirect isn't the boundary.
- **Access to other people's data.** I read the ownership check on every route that takes an ID, and
  each one filters by owner.
- **Web output.** React escapes everything. The one `dangerouslySetInnerHTML` is a static theme
  script, and stored links must start with `http://` or `https://`.
- **Secrets.** None in the repository, and CI scans for them.

## Risks accepted for a portfolio deploy

Each of these would change with real users or a paying service.

- **No Content-Security-Policy on web pages.** Next's inline scripts need nonces, which don't work
  with the prerendering this app uses. With the output above, a CSP would be a second layer, not the
  only one.
- **Tokens are stored in plain text.** They have to be shown again, so they can't be hashed. Anyone
  with the database could open every link, but they could also read the data those links show.
- **Solves queue without a limit.** A signed-in user gets 120 an hour, and on the free plan each
  takes 15 s, so even one account could keep everyone else waiting. They could slow the planner but
  not break it.
- **Signed-in writes have no overall rate limit.** Plans keep their old versions, so one determined
  account could fill Neon's 0.5 GB, slowly, at up to 120 versions an hour.
- **`TRUSTED_PROXY_HOPS=1` is unverified on Render.** Render doesn't document its forwarding chain.
  If it's wrong, visitors share one per-address count, so limits would trip early. It can't be
  forged, because the rightmost entry comes from Render's own proxy.
- **The demo user can still edit its own Clerk profile.** Tickets don't need a password, so changing
  it locks nobody out. MFA must stay off on this Clerk instance (`docs/deploy.md`).
- **`/docs` and `/openapi.json` are public.** The repository is too.
- **An imported recipe's photo loads from its own site.** That site sees the viewer's address.
