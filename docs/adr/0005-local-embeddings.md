# ADR-0005: Local embeddings with fastembed (bge-small-en-v1.5)

- Status: Accepted
- Date: 2026-10-08

## Context

Ingredient normalisation needs nearest-neighbour search from free-text names ("raw tiger
prawns") to USDA foods, and recipes need vectors for candidate search and craving similarity.
The plan stores vectors in Postgres (pgvector). Options for producing them:

1. **Hosted embeddings API** (e.g. Voyage AI, which Anthropic recommends). Strong models, but a
   paid service, an API key locally and in CI, network calls in the pipeline, and results that
   depend on a remote model version.
2. **Local model via fastembed** (ONNX runtime, no PyTorch). `BAAI/bge-small-en-v1.5`: 384
   dimensions, ~65 MB download, CPU-fast (8.3k foods embed in ~90 s).
3. **No embeddings yet**: trigram fuzzy match + aliases only. Simplest, but contradicts the plan
   and gives nothing for semantic matches ("scallion" → "Onions, spring").

## Decision

Option 2. The `Embedder` protocol keeps the model swappable; every stored vector records its
model name, and re-embedding replaces vectors from other models.

## Consequences

- Free, offline, deterministic; CI caches the model with the other downloads.
- Adds `onnxruntime` and `tokenizers` to the data package only; the API image doesn't ship them.
- A small model is weak on single-word queries ("paprika" alone retrieves junk), which is why
  matching combines vectors with lexical retrieval and a rerank (ADR-0006). Swapping in a
  bigger model is a re-embed plus `larder-data report --evaluate` to compare.
