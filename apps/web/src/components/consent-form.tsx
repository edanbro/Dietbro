"use client";

import Link from "next/link";
import { useState } from "react";

import { ErrorAlert } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { type Me, useConsent } from "@/lib/api/hooks";
import { APP_NAME } from "@/lib/brand";

/**
 * Setup's first step: the terms, and the explicit consent GDPR Article 9 asks for before health
 * data is kept. Two boxes, not one, since consent can't be bundled into agreeing to terms.
 */
export function ConsentForm({ onSaved }: { onSaved: (me: Me) => void }) {
  const consent = useConsent();
  const [terms, setTerms] = useState(false);
  const [health, setHealth] = useState(false);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    consent.mutate(undefined, { onSuccess: onSaved });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Consent">
      <p className="text-sm text-muted-foreground">
        To plan around your body, goals and allergies, {APP_NAME} keeps health information about
        you, so the law asks for your clear agreement first. Read the{" "}
        <Link href="/terms" className="text-foreground underline underline-offset-4">
          Terms
        </Link>{" "}
        and the{" "}
        <Link href="/privacy" className="text-foreground underline underline-offset-4">
          Privacy policy
        </Link>
        .
      </p>
      <div className="flex items-start gap-3">
        <Checkbox
          id="consent-terms"
          checked={terms}
          onCheckedChange={(on) => setTerms(on)}
          className="mt-0.5"
        />
        <Label htmlFor="consent-terms" className="leading-snug font-normal">
          I&apos;m 18 or over and I agree to the Terms.
        </Label>
      </div>
      <div className="flex items-start gap-3">
        <Checkbox
          id="consent-health"
          checked={health}
          onCheckedChange={(on) => setHealth(on)}
          className="mt-0.5"
        />
        <Label htmlFor="consent-health" className="leading-snug font-normal">
          I agree that {APP_NAME} can keep and use my health information (height, weight, goals,
          allergies, diet and what I eat) to plan my meals. I can withdraw this at any time by
          deleting my account.
        </Label>
      </div>
      <Button type="submit" disabled={!terms || !health || consent.isPending}>
        Agree and continue
      </Button>
      <ErrorAlert error={consent.error} />
    </form>
  );
}
