"""Plan changes and what they need: the executor (replan), safe recipe search, off-plan
estimates, food matching, drafted recipes, and the model budget and replan lock (limits).
The changes are typed (larder_llm.schemas); the plan screen and the diary send them through
POST /plans/replan (larder_api.replans). See docs/adr/0015 and docs/adr/0018."""
