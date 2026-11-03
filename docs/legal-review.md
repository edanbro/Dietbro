# Legal, privacy and accessibility review

Reviewed on 2026-11-03, a day after the first public deploy. The method was the same as the
[security review](security-review.md): read what the code stores and sends, then check the live
site in a browser (its cookies, storage and requests) instead of assuming. This is a careful
reading of the rules by the project's main coder, not legal advice. The open risks at the end are
the ones to put to a solicitor before Mealwright charges money or takes on many users.

## Which rules apply

Mealwright is run by one person in Ireland, for people in Ireland and the UK.

- **GDPR** and the **Data Protection Act 2018**. Weight, allergies, diet, goals and the food diary
  are health data, a special category under Article 9, so they need explicit consent. The Irish
  regulator is the Data Protection Commission (DPC).
- **ePrivacy Regulations 2011** (S.I. 336/2011, Regulation 5). Storing anything on a visitor's
  device needs consent unless it's strictly necessary for a service they asked for. The DPC's 2020
  guidance reads that exemption narrowly and says analytics always need consent.
- **Consumer law.** The Consumer Rights Act 2022 controls unfair terms. EU consumers keep their own
  country's mandatory law and courts (Rome I Article 6, Brussels I Article 18). A free personal
  project may not count as a "trader", but the terms are written as if it does.
- **Digital Services Act.** Share links make Mealwright a hosting service. Micro-enterprises are
  spared most duties, but not a contact point, clear terms, a way to report content and reasons
  when it's removed (Articles 11, 12, 14, 16 and 17).
- **European Accessibility Act** (S.I. 636/2023). It covers consumer e-commerce, and exempts
  micro-enterprises. Mealwright is neither e-commerce nor bigger than one person, so it's out of
  scope, but it keeps WCAG 2.1 AA anyway.
- **Copyright** (Copyright and Related Rights Act 2000) and the licences of the data it uses.
- **UK users:** UK GDPR and PECR, which have the same shape (see the UK representative below).

## Found and fixed

| Severity | Finding | Evidence | Fix |
|---|---|---|---|
| High | Health data was kept without explicit consent (Article 9) | Read the code: setup saved body, goals and allergies straight away | A first setup step with two boxes, terms and health data, recorded with a timestamp each (`users.terms_accepted_at`, `health_consent_at`). Plans need it, so existing accounts are asked before their next plan |
| High | No privacy policy, terms or cookie policy (Articles 12 and 13) | None in the app | `/privacy`, `/terms` and `/cookies`, linked from the landing page, the sign-up page, the profile and each other |
| Medium | Clerk's telemetry went from every visitor's browser to `clerk-telemetry.com` and stored `clerk_telemetry_throttler` in local storage. It isn't strictly necessary, so it needed consent | Seen in the live site's requests and storage | Off (`telemetry={false}`), so no consent banner is needed |
| Medium | The shared demo didn't say that what a visitor types, the next one sees | Read the code | A notice on every page while signed in as the demo |
| Low | Recipe photos sent the site's address as a referrer to TheMealDB and recipe sites | `RecipeArt` had no referrer policy | `referrerPolicy="no-referrer"`, as product photos already had |
| Low | "Allergies are hard rules ... Always." promised more than the data can | The data under the check is partly crowdsourced | "Still check labels: product data can be wrong." |
| Low | TheMealDB's credit didn't say its photos belong to its users, as its terms ask | Its terms of use | The data sources page says so |

## Checked and fine

- **No analytics, ads or tracking.** No analytics or ad scripts or pixels, and no embedded
  iframes. Clerk loads through our own `/__clerk` proxy, and the fonts are self-hosted by
  `next/font`, so no Google Fonts request.
- **Cookies.** After the fix, the live site sets only Clerk's sign-in cookies (`__session`,
  `__client_uat`, `__clerk_db_jwt`, `clerk_active_context`, and suffixed copies). Local storage
  holds the theme, offline copies of the plan (`mw:…`, cleared on sign-out) and Clerk's settings
  cache. All of these are strictly necessary, so the cookie policy explains them and there's no
  banner.
- **Third-party content** is images only: product photos from Open Food Facts, recipe photos
  from TheMealDB, and imported recipes' photos from their own sites. In a check, TheMealDB's and
  Open Food Facts' image servers set no cookies. These sites still see a visitor's IP address,
  which the privacy policy says. Proxying the photos through our server would hide that, but it
  costs bandwidth on the free plan.
- **Data minimisation.** The app keeps a birth year rather than a birth date. Body stats are
  optional and can be removed on their own. Receipt photos are deleted once read, and receipt
  text once confirmed. Model calls are logged without their text. Share pages leave out the
  pantry, goals, weight, allergies and name. Export and delete cover everything.
- **Data sent to the model:** only food words (what someone typed for a meal they had, or a name
  the offline matcher couldn't place), with no name or email. The demo never calls it.
- **Images and copyright.** The landing and README screenshots are of the app itself. The
  TheMealDB photos in them are credited under its terms. Icons are Lucide (ISC), and the fonts
  are Figtree and Fraunces (SIL Open Font License). Open Food Facts photos are CC BY-SA and
  credited. There are no stock photos.
- **Age.** The terms say 18 or over, and the API already refuses body stats under 18
  (`larder_core.energy.MIN_AGE`). That is stricter than Ireland's digital age of consent, which
  is 16, because calorie plans aren't for teenagers.
- **Accessibility.** Every page, light and dark, runs axe's WCAG 2.1 A/AA rules in CI
  (`e2e/pages.e2e.ts`), now including the four legal pages. The design pass (#64 to #67) set the
  contrast tokens and keyboard access. In the new UI the consent boxes are labelled, links in
  policy text are underlined (not just a different colour), and the demo notice uses the `info`
  tokens. Landing screenshots have descriptive alt text. Recipe and product photos have empty
  alt text because the name is printed next to them, so a screen reader would hear it twice.

## Risks left open

Each of these would change with real users, money or a bigger beta.

- **TheMealDB's free key.** Its API page allows the test key "1" "during development of your app
  or for educational use", and asks for a paid supporter key to publish in an app store. A free
  portfolio website is closest to educational use. With beta users or any income, either become a
  supporter (paid: ask Eduard) or plan from the curated recipes only. Most TheMealDB photos are
  uploads of unknown origin, and TheMealDB handles takedown requests for them.
- **Clerk's development instance.** Clerk says not to use one in production: it shows a badge,
  caps the number of users and shares its social sign-in credentials. Its "Secured by" badge on the
  sign-in and sign-up forms, grey on orange, also fails WCAG contrast (2.0:1), and only a
  production instance removes it. That needs a domain, roughly €10 to €15 a year, which is a
  running cost to check with Eduard.
- **A UK representative.** UK GDPR Article 27 asks controllers outside the UK that serve UK users to
  name one. It exempts occasional, low-risk processing, which a health-data service probably isn't.
  It's a paid service, so decide before inviting UK users.
- **Withdrawing consent** means deleting the account (or removing body stats, or emailing).
  Article 7(3) wants withdrawal as easy as giving consent, and here both take two steps. If users
  ask, a button that deletes only the health data is better.
- **Inactive accounts** are kept until deleted. `users.last_seen_at` is written but never read.
  A rule that deletes accounts unused for two years would use it and close this.
- **No impact assessment (DPIA).** One isn't required unless health data is processed on a large
  scale. Write one before the beta grows past friends and family.
- **Medical device rules.** The app makes no medical claims. If it ever claimed to treat or manage
  a condition, such as diabetes, the EU Medical Devices Regulation could apply.
- **No licence file.** The code is "all rights reserved" by default, which matches the terms. Add a
  licence if others should be able to reuse it.
- **Accessibility beyond axe.** Automated checks find only part of what a real screen-reader test
  would. None has been done.

## What only Eduard can do

- Data processing agreements (Article 28): check each provider's covers this account. Most are
  part of their terms of service, and a few have to be accepted in the dashboard.
- Answer rights requests at the published email within a month.
- If personal data leaks, tell the DPC within 72 hours unless it's unlikely to harm anyone
  (Article 33).

## Record of processing (Article 30)

Small organisations are excused from keeping one, unless they process special category data. This
one does, so here it is.

| Purpose | Data | Legal basis | Who else | Kept |
|---|---|---|---|---|
| Sign-in | Email, password or social profile | Contract, 6(1)(b) | Clerk (US) | Until the account is deleted |
| Plans that fit the person | Body stats, weight log, goals, allergies, avoided foods, diet, food diary | Explicit consent, 9(2)(a) | Render, Neon, Vercel; Anthropic for food words | Until deleted |
| Kitchen and plans | Region, pantry, receipts, shopping lists, plans, recipes, notes, templates | Contract, 6(1)(b) | Render, Neon, Vercel | Until deleted; receipt photos once read |
| Reminders, calendar, sharing | Push subscription, random tokens | Contract, 6(1)(b), switched on by the user | Browser push services | Until switched off or deleted |
| Security and cost limits | IP addresses in logs, request counts, model call sizes and costs | Legitimate interests, 6(1)(f) | Render, Vercel, Upstash | Logs as each host keeps them; counts at most a day; model calls until deleted |

Transfers to the US rely on the EU–US Data Privacy Framework or standard contractual clauses in
each provider's terms. Security measures are in the [security review](security-review.md).

## Keeping it true

The policies describe what the code does. When a change adds personal data, a cookie or a
third party, update `/privacy`, `/cookies` and this file in the same PR. If it needs new consent,
reset the timestamps so people are asked again.
