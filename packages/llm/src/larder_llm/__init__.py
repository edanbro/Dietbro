"""The language layer (PLAN §7): the Claude client for small structured calls, the typed plan
changes every screen sends (schemas) and what a replan reports back (outcome).

Pure apart from the Anthropic client: no database, no planner (larder_api.changes binds the
changes to the signed-in user and the database)."""
