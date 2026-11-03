import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, Section } from "@/components/legal-page";
import { APP_NAME } from "@/lib/brand";
import { CONTACT_EMAIL, OPERATOR } from "@/lib/legal";

export const metadata: Metadata = { title: "Terms" };

const Email = () => <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>;

export default function TermsPage() {
  return (
    <LegalPage title="Terms of use" current="/terms">
      <p>
        These terms are the agreement between you and {OPERATOR}, who runs {APP_NAME} in Ireland
        as a free personal project. By creating an account or using the demo, you agree to them.
        Questions: <Email />.
      </p>

      <Section title="Who can use it">
        <p>
          You must be 18 or over. Keep your sign-in to yourself, and tell us if you think
          someone else has used it.
        </p>
      </Section>

      <Section title="Not medical advice">
        <p>
          {APP_NAME} is a planning tool for healthy adults. It isn&apos;t medical or dietary
          advice, and calorie and nutrient figures are estimates. If you have a medical
          condition, are pregnant or breastfeeding, have or have had an eating disorder, or are
          changing your weight a lot, talk to a doctor or dietitian before following a plan.
        </p>
      </Section>

      <Section title="Allergies and food safety">
        <p>
          {APP_NAME} leaves out recipes with the allergens and foods you list, using product and
          recipe information that can be incomplete or wrong (much of it is crowdsourced).{" "}
          <strong>Always check labels and ingredients yourself</strong>, and don&apos;t rely on{" "}
          {APP_NAME} alone for a serious allergy. Storing, cooking and checking food is safe to
          eat, including use-by dates, is up to you.
        </p>
        <p>Prices, pack sizes and what&apos;s in your pantry are estimates too.</p>
      </Section>

      <Section title="Your content">
        <p>
          What you add stays yours. You let {APP_NAME} store and use it to run the service for
          you, and to show it to anyone you give a share link or calendar feed to. Anyone with
          such a link can see what it shows until you turn it off.
        </p>
        <p>
          Only import or share recipes, notes and photos you&apos;re allowed to. Imported
          recipes are for your own use: sharing someone else&apos;s recipe text or photos
          publicly may need their permission.
        </p>
      </Section>

      <Section title="Fair use">
        <p>Don&apos;t:</p>
        <ul>
          <li>break the law with it, or share anything unlawful or harmful through it;</li>
          <li>try to get into other people&apos;s accounts or data;</li>
          <li>overload it, scrape it, or get around its limits;</li>
          <li>put anything personal, offensive or misleading in the shared demo.</li>
        </ul>
        <p>
          If you find a security problem, please tell us at <Email /> instead of testing it on
          other people&apos;s data.
        </p>
      </Section>

      <Section title="Reporting content">
        <p>
          To report a share link that breaks the law or someone&apos;s rights, email <Email />{" "}
          with the link and why. Reports are read and answered, and content that breaks these
          terms is taken down and the person who shared it told why. Accounts that seriously or
          repeatedly break these terms can be suspended or closed.
        </p>
      </Section>

      <Section title="The service">
        <p>
          {APP_NAME} is free and runs on free hosting, so it can be slow, change, pause or stop,
          and features can be added or removed. If it is going to close for good, the site will
          say so in advance where possible, so you can download your data.
        </p>
      </Section>

      <Section title="Data and recipes from others">
        <p>
          Food data, recipes and photos come from the sources on the{" "}
          <Link href="/attributions">data sources</Link> page, under their own licences. The
          rest of {APP_NAME}, including its design and text, belongs to {OPERATOR}.
        </p>
      </Section>

      <Section title="Liability">
        <p>
          {APP_NAME} is provided free and as it is. As far as the law allows, {OPERATOR}
          isn&apos;t liable for loss you could have avoided by following these terms (such as
          checking labels), for indirect loss, or for loss of data you could have downloaded.
        </p>
        <p>
          Nothing in these terms limits liability for death or personal injury caused by
          negligence, for fraud, or for anything else that can&apos;t be limited by law, and
          they don&apos;t affect your rights as a consumer.
        </p>
      </Section>

      <Section title="Ending">
        <p>
          You can stop at any time by deleting your account (Profile, then Your data). The{" "}
          <Link href="/privacy">privacy policy</Link> explains what happens to your data.
        </p>
      </Section>

      <Section title="Changes and law">
        <p>
          When these terms change, so does the date at the top, and significant changes will be
          announced on the site before they apply. Irish law governs these terms. If you live
          elsewhere in the EU or the UK, you keep the protection of your own country&apos;s
          consumer law and can bring a claim in its courts.
        </p>
      </Section>
    </LegalPage>
  );
}
