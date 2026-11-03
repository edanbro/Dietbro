import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, Section } from "@/components/legal-page";
import { APP_NAME } from "@/lib/brand";
import { CONTACT_EMAIL, OPERATOR } from "@/lib/legal";

export const metadata: Metadata = { title: "Privacy policy" };

// Written from what the code does (docs/legal-review.md): update both when that changes.

const Email = () => <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>;

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy policy" current="/privacy">
      <p>
        What {APP_NAME} keeps about you, why, who else handles it, and your rights. In short: it
        keeps what it needs to plan your meals, never sells it or shows ads, and uses no
        analytics or tracking.
      </p>

      <Section title="Who is responsible">
        <p>
          {APP_NAME} is a free personal project run by {OPERATOR} in Ireland, who is the
          controller of your personal data under the GDPR. For anything in this policy, email{" "}
          <Email />.
        </p>
      </Section>

      <Section title="What it keeps, and why">
        <ul>
          <li>
            <strong>Your account:</strong> your email address and how you sign in (a password,
            or the basic profile a social sign-in shares if you use one). Clerk keeps these so you
            can sign in. The legal basis is providing the service you signed up for (GDPR
            Article 6(1)(b)).
          </li>
          <li>
            <strong>Where you are:</strong> country, time zone, date format, units and currency,
            so plans use local foods, prices and dates. Article 6(1)(b).
          </li>
          <li>
            <strong>Health information:</strong> sex, age (kept as a birth year), height, weight
            and activity if you add them, your weight log, calorie and nutrient goals, allergies,
            foods you avoid, your diet, and the diary of what you ate. This is health data, a
            special category under Article 9, so {APP_NAME} keeps it only with the explicit
            consent you give when you set up (Articles 9(2)(a) and 6(1)(a)).
          </li>
          <li>
            <strong>Your kitchen and plans:</strong> your pantry, the receipts you add, shopping
            lists, meal plans and their earlier versions, recipes you import or edit, notes,
            ratings, favourites and saved weeks. Article 6(1)(b).
          </li>
          <li>
            <strong>What you turn on:</strong> reminders (an address your browser gives for
            notifications), a calendar feed and share links (random addresses that show only what
            you chose to share). Article 6(1)(b), and you can turn each one off.
          </li>
          <li>
            <strong>Security and costs:</strong> the hosts&apos; server logs, which include IP
            addresses; counts of requests per IP address or account for rate limits, kept for at
            most a day; and a record of each request to the AI model (its size and cost, not its
            words) to cap spending per account. The basis is our legitimate interest in keeping
            the service secure and affordable (Article 6(1)(f)).
          </li>
        </ul>
        <p>
          A receipt photo is deleted once it has been read, and a receipt&apos;s text once you
          confirm its items. {APP_NAME} doesn&apos;t make decisions about you with legal or
          similarly significant effects: it suggests meals, and you choose what to eat.
        </p>
      </Section>

      <Section title="Who else handles it">
        <p>
          These companies run parts of {APP_NAME}, under data processing terms that let them use
          your data only to provide their service:
        </p>
        <ul>
          <li>
            <strong>Clerk</strong> (US): sign-in and accounts.
          </li>
          <li>
            <strong>Vercel</strong> (US): hosts the website.
          </li>
          <li>
            <strong>Render</strong> (servers in Frankfurt): runs the server that plans meals.
          </li>
          <li>
            <strong>Neon</strong> (database in Frankfurt): stores your data.
          </li>
          <li>
            <strong>Upstash</strong> (servers in Ireland): counts requests for the rate limits.
          </li>
          <li>
            <strong>Anthropic</strong> (US): when {APP_NAME} can&apos;t match a food name by
            itself, it can ask Anthropic&apos;s Claude model. It sends only the words for the
            food, such as what you typed for a meal you had, never your name or email.
            Anthropic doesn&apos;t train its models on this.
          </li>
          <li>
            <strong>Your browser&apos;s push service</strong> (Google, Mozilla, Apple or
            Microsoft), only if you turn reminders on. Reminders are encrypted, so the push
            service can&apos;t read them.
          </li>
        </ul>
        <p>
          Some photos load straight from other sites: product photos from Open Food Facts,
          recipe photos from TheMealDB, and an imported recipe&apos;s photo from its own site.
          Like any website, those sites see your IP address and browser when a photo loads.{" "}
          {APP_NAME} asks your browser not to tell them which page you were on.
        </p>
        <p>
          When you scan a barcode {APP_NAME} doesn&apos;t know, its server looks up only that
          barcode on Open Food Facts. When you import a recipe from a link, its server fetches
          the page, so that site sees our server, not you.
        </p>
      </Section>

      <Section title="Outside the EU">
        <p>
          Clerk, Vercel and Anthropic can process data in the US, and the other providers are US
          companies. Those transfers rely on the EU–US Data Privacy Framework where the provider
          is certified, and otherwise on the European Commission&apos;s standard contractual
          clauses in the provider&apos;s data processing terms.
        </p>
      </Section>

      <Section title="How long it's kept">
        <ul>
          <li>Your account and everything in it: until you delete your account.</li>
          <li>Receipts: as above, deleted once read and confirmed.</li>
          <li>Server logs: a short time, set by each host, for security and fixing faults.</li>
          <li>
            After you delete your account, copies can stay in the database&apos;s short-term
            backups for at most a few days.
          </li>
        </ul>
      </Section>

      <Section title="Your rights">
        <ul>
          <li>
            <strong>Get a copy</strong> of everything {APP_NAME} keeps about you, in a file you can
            take elsewhere: Profile, then Your data, then Download my data.
          </li>
          <li>
            <strong>Correct it</strong> in your profile at any time.
          </li>
          <li>
            <strong>Delete it:</strong> Profile, then Your data, then Delete my account removes
            your data and your sign-in. Body stats can also be removed on their own.
          </li>
          <li>
            <strong>Withdraw your consent</strong> to keeping health information at any time, by
            deleting your account: planning needs that information, so the account can&apos;t
            stay without it. Withdrawing doesn&apos;t make earlier use unlawful.
          </li>
          <li>
            <strong>Object or ask for a restriction</strong> of the processing for security and
            costs, by email.
          </li>
        </ul>
        <p>
          Email <Email /> for any of these or anything else; you&apos;ll get an answer within a
          month. You can also complain to the{" "}
          <a href="https://www.dataprotection.ie">Data Protection Commission</a>, Ireland&apos;s
          regulator, or to the regulator where you live.
        </p>
      </Section>

      <Section title="Adults only">
        <p>{APP_NAME} is for people aged 18 or over.</p>
      </Section>

      <Section title="The demo">
        <p>
          The demo is one account shared by everyone who opens it, with made-up data that is
          reset every day. Anyone can see what is entered there, so don&apos;t put anything
          about yourself in it.
        </p>
      </Section>

      <Section title="Security">
        <p>
          Connections are encrypted, every request is checked against your own account, and the
          code was reviewed for security before launch. No system is perfectly secure: if you
          find a problem, please email <Email />.
        </p>
      </Section>

      <Section title="Changes">
        <p>
          When this policy changes, so does the date at the top. Significant changes will be
          announced on the site before they apply. Cookies and similar storage are covered in
          the <Link href="/cookies">cookie policy</Link>.
        </p>
      </Section>
    </LegalPage>
  );
}
