"""The language layer (PLAN §7): Claude clients, the typed changes and tools the model uses,
the agent loop, and the offline rule parser that stands in when no model is available.

Pure apart from the Anthropic client: no database, no planner. The API binds tool handlers to
the signed-in user and the database (larder_api.chat)."""
