# ADR-0001: Record architecture decisions

- Status: Accepted
- Date: 2026-10-08

## Context

Design choices on this project must be explainable later (including in interviews). Reasons get
lost if they live only in chat or PR threads.

## Decision

Write an ADR for every decision made between real alternatives. Format: short Markdown file in
`docs/adr/NNNN-title.md` with Status, Context, Decision, Consequences (Michael Nygard's template).
ADRs are immutable once accepted; a change of mind is a new ADR that supersedes the old one.
`docs/DESIGN.md` describes the current system and links to ADRs for the "why".

## Consequences

- Small writing cost per decision; a reviewable history of trade-offs.
- Trivial or forced choices (no real alternative) don't get an ADR.
