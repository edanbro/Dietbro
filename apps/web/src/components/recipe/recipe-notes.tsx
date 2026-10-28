"use client";

import { cn } from "cn";
import { StarIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { type Recipe, useRecipeFeedback, useRecipeNote } from "@/lib/api/hooks";

const STARS = [1, 2, 3, 4, 5] as const;

/**
 * The user's own note ("more chilli next time") and a 1-5 star rating. Private, and the
 * planner doesn't read them: a 5 offers "Add to favourites" and a 1 "Never again", which do
 * steer it. The note shows again at the top of cook mode.
 */
export function RecipeNotes({ recipe }: { recipe: Recipe }) {
  const save = useRecipeNote(recipe.id);
  const feedback = useRecipeFeedback(recipe.id);
  const saved = recipe.note ?? null;
  const [text, setText] = useState(saved?.note ?? "");
  const rating = saved?.rating ?? null;

  function rate(stars: number) {
    const next = stars === rating ? null : stars; // the current rating again clears it
    save.mutate(
      { note: saved?.note ?? null, rating: next },
      {
        onSuccess: () => {
          if (next === 5 && recipe.feedback !== "favourite") {
            toast.success("Rated 5 stars", {
              action: { label: "Add to favourites", onClick: () => feedback.mutate("favourite") },
            });
          } else if (next === 1 && recipe.feedback !== "never") {
            toast.success("Rated 1 star", {
              action: { label: "Never plan it again", onClick: () => feedback.mutate("never") },
            });
          }
        },
      },
    );
  }

  const changed = text.trim() !== (saved?.note ?? "");
  return (
    <section aria-labelledby="recipe-notes" className="flex flex-col gap-2">
      <h2 id="recipe-notes" className="text-base font-semibold">
        Your notes
      </h2>
      <div role="radiogroup" aria-label="Your rating" className="flex items-center gap-1">
        {STARS.map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={rating === n}
            aria-label={`${n} ${n === 1 ? "star" : "stars"}`}
            disabled={save.isPending}
            onClick={() => rate(n)}
            className="rounded-md p-1 outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <StarIcon
              aria-hidden
              className={cn(
                "size-6",
                rating !== null && n <= rating
                  ? "fill-amber-400 text-amber-500"
                  : "text-muted-foreground",
              )}
            />
          </button>
        ))}
        <span className="ml-1 text-xs text-muted-foreground">Only you see these</span>
      </div>
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(
            { note: text.trim() || null, rating },
            { onSuccess: () => toast.success(text.trim() ? "Note saved" : "Note removed") },
          );
        }}
      >
        <label htmlFor="recipe-note" className="sr-only">
          Note
        </label>
        <textarea
          id="recipe-note"
          rows={3}
          maxLength={1000}
          placeholder="e.g. More chilli next time; 10 minutes less in our oven"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="rounded-md border border-field bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        {changed ? (
          <Button type="submit" size="sm" className="self-start" disabled={save.isPending}>
            Save note
          </Button>
        ) : null}
        <ErrorAlert error={save.error} />
      </form>
    </section>
  );
}
