"use client";

import { PencilIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type PlanTemplate,
  useDeleteTemplate,
  useRenameTemplate,
  useTemplates,
} from "@/lib/api/hooks";

function Row({ template }: { template: PlanTemplate }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(template.name);
  const rename = useRenameTemplate();
  const remove = useDeleteTemplate();
  if (editing) {
    return (
      <li>
        <form
          aria-label={`Rename ${template.name}`}
          className="flex items-center gap-2 py-2"
          onSubmit={(e) => {
            e.preventDefault();
            rename.mutate(
              { id: template.id, name: name.trim() },
              { onSuccess: () => setEditing(false) },
            );
          }}
        >
          <Input
            aria-label="Template name"
            required
            maxLength={60}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <Button type="submit" size="sm" disabled={rename.isPending || !name.trim()}>
            Save
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </form>
        <ErrorAlert error={rename.error} />
      </li>
    );
  }
  return (
    <li className="flex items-start gap-2 py-2">
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="font-medium">{template.name}</span>
        <span className="text-xs text-muted-foreground">
          {template.meals} meals{template.recipes.length ? `: ${template.recipes.join(", ")}` : ""}
        </span>
      </div>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Rename ${template.name}`}
        onClick={() => setEditing(true)}
      >
        <PencilIcon />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Delete ${template.name}`}
        disabled={remove.isPending}
        onClick={() =>
          remove.mutate(template.id, {
            onSuccess: () => toast.success(`Deleted "${template.name}"`),
          })
        }
      >
        <Trash2Icon />
      </Button>
    </li>
  );
}

/** Saved weeks of meals ("Save as template" on the plan), to rename or delete. */
export function TemplatesForm() {
  const templates = useTemplates();
  if (templates.isPending) return null;
  if (templates.error) {
    return <ErrorAlert error={templates.error} onRetry={() => void templates.refetch()} />;
  }
  if (!templates.data.length) {
    return (
      <p className="text-sm text-muted-foreground">
        None yet. Save a week you liked with &ldquo;Save as template&rdquo; on your plan, then plan
        it again from &ldquo;New plan&rdquo;.
      </p>
    );
  }
  return (
    <ul className="flex flex-col divide-y" aria-label="Templates">
      {templates.data.map((t) => (
        <Row key={t.id} template={t} />
      ))}
    </ul>
  );
}
