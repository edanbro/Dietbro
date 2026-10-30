"use client";

import { LinkIcon, PlusIcon, TriangleAlertIcon, XIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, LabeledInput, NativeSelect } from "@/components/form-bits";
import { SLOT_LABEL } from "@/components/plan/slots";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type ImportDraft,
  type Slot,
  useEditRecipe,
  useImportRecipe,
  useReadRecipePage,
} from "@/lib/api/hooks";

const SLOTS: Slot[] = ["breakfast", "lunch", "dinner", "snack"];

type Line = ImportDraft["ingredients"][number] & { key: string };

const blank = (): Line => ({ key: crypto.randomUUID(), line: "", name: "", quantity: "" });

export const EMPTY_DRAFT: ImportDraft = {
  name: "",
  slot: "dinner",
  servings: 2,
  ingredients: [],
  instructions: "",
};

/**
 * The editable draft: everything read from the page can be changed before saving. With
 * `editing`, it saves changes to that recipe instead (the user's own in place; a catalogue
 * recipe as their own copy).
 */
export function DraftForm({
  initial,
  onBack,
  editing,
}: {
  initial: ImportDraft;
  onBack: () => void;
  editing?: number;
}) {
  const router = useRouter();
  const create = useImportRecipe();
  const change = useEditRecipe(editing ?? 0);
  const save = editing === undefined ? create : change;
  const [draft, setDraft] = useState<ImportDraft>(initial);
  const [lines, setLines] = useState<Line[]>(() => {
    const read = initial.ingredients.map((i) => ({ ...i, key: crypto.randomUUID() }));
    return read.length ? read : [blank(), blank()];
  });
  const problems = save.data?.problems ?? [];

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const ingredients = lines
      .filter((l) => l.name.trim())
      .map(({ line, name, quantity }) => ({ line, name: name.trim(), quantity: quantity.trim() }));
    save.mutate(
      { ...draft, name: draft.name.trim(), ingredients },
      {
        onSuccess: (result) => {
          if (result.recipe_id === null) return;
          toast.success(
            editing === undefined || result.copied
              ? `Saved ${draft.name.trim()} to your recipes`
              : "Changes saved",
          );
          router.push(`/recipes/${result.recipe_id}`);
        },
      },
    );
  }

  const setLine = (key: string, patch: Partial<Line>) =>
    setLines((all) => all.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  return (
    <form onSubmit={submit} className="flex flex-col gap-5" aria-label="Recipe to save">
      {draft.image_url ? (
        // The page's own photo, shown as the site serves it.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={draft.image_url} alt="" className="aspect-[3/1] w-full rounded-xl object-cover" />
      ) : null}
      <LabeledInput
        id="import-name"
        label="Name"
        required
        maxLength={120}
        value={draft.name}
        onChange={(e) => setDraft({ ...draft, name: e.target.value })}
      />
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="import-slot">Meal</Label>
          <NativeSelect
            id="import-slot"
            value={draft.slot}
            onChange={(e) => setDraft({ ...draft, slot: e.target.value as Slot })}
          >
            {SLOTS.map((s) => (
              <option key={s} value={s}>
                {SLOT_LABEL[s]}
              </option>
            ))}
          </NativeSelect>
        </div>
        <LabeledInput
          id="import-servings"
          label="Serves"
          type="number"
          min={1}
          max={8}
          required
          value={draft.servings}
          onChange={(e) => setDraft({ ...draft, servings: Number(e.target.value) })}
        />
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">Ingredients</legend>
        <p className="text-xs text-muted-foreground">
          Amount for the whole recipe, then a plain name (&quot;olive oil&quot;, not a brand).
        </p>
        <ul className="flex flex-col gap-2">
          {lines.map((l, i) => (
            <li key={l.key} className="flex flex-col gap-1">
              <div className="flex gap-2">
                <Input
                  aria-label={`Amount ${i + 1}`}
                  placeholder="200 g"
                  className="w-28"
                  maxLength={40}
                  value={l.quantity}
                  onChange={(e) => setLine(l.key, { quantity: e.target.value })}
                />
                <Input
                  aria-label={`Ingredient ${i + 1}`}
                  placeholder="chicken breast"
                  className="flex-1"
                  maxLength={120}
                  value={l.name}
                  onChange={(e) => setLine(l.key, { name: e.target.value })}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove ingredient ${i + 1}`}
                  onClick={() => setLines((all) => all.filter((x) => x.key !== l.key))}
                >
                  <XIcon />
                </Button>
              </div>
              {l.line ? (
                <span className="pl-1 text-xs text-muted-foreground">From the page: {l.line}</span>
              ) : null}
            </li>
          ))}
        </ul>
        {lines.length < 25 ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="self-start"
            onClick={() => setLines((all) => [...all, blank()])}
          >
            <PlusIcon aria-hidden />
            Add ingredient
          </Button>
        ) : null}
      </fieldset>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="import-method">Method</Label>
        <textarea
          id="import-method"
          rows={8}
          maxLength={4000}
          required
          className="rounded-md border border-field bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          value={draft.instructions}
          onChange={(e) => setDraft({ ...draft, instructions: e.target.value })}
        />
      </div>

      {problems.length ? (
        <Alert role="alert" className="border-warning/50">
          <TriangleAlertIcon aria-hidden />
          <AlertTitle>Fix these and save again</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
      <ErrorAlert error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Checking…" : editing === undefined ? "Save recipe" : "Save changes"}
        </Button>
        <Button type="button" variant="ghost" onClick={onBack}>
          {editing === undefined ? "Start again" : "Cancel"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Nutrition, allergens and diet are worked out from our food data, and the recipe is checked
        against your allergies like every other. Only you can see it.
      </p>
    </form>
  );
}

/** Import a recipe: read it from a link, or type it in, then check and save. */
export function RecipeImport() {
  const read = useReadRecipePage();
  const [url, setUrl] = useState("");
  const [draft, setDraft] = useState<ImportDraft | null>(null);

  if (draft) {
    return (
      <DraftForm
        initial={draft}
        onBack={() => {
          setDraft(null);
          read.reset();
        }}
      />
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <form
        className="flex flex-col gap-2"
        aria-label="Read a recipe from a link"
        onSubmit={(e) => {
          e.preventDefault();
          read.mutate(url, { onSuccess: setDraft });
        }}
      >
        <Label htmlFor="import-url">Recipe link</Label>
        <div className="flex gap-2">
          <Input
            id="import-url"
            type="url"
            inputMode="url"
            required
            placeholder="https://www.bbcgoodfood.com/recipes/…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <Button type="submit" disabled={read.isPending}>
            <LinkIcon aria-hidden />
            {read.isPending ? "Reading…" : "Read"}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Works with most recipe sites. You can check everything before it&apos;s saved.
        </p>
      </form>
      <ErrorAlert error={read.error} />
      <Button variant="outline" className="self-start" onClick={() => setDraft(EMPTY_DRAFT)}>
        Type a recipe in instead
      </Button>
    </div>
  );
}
