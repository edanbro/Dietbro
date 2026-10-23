"""Evals (PLAN M7): seeded scenarios, two planners, one validator.

- `scenarios`: synthetic users over the synthetic catalogue (no database; what CI runs) or over
  the seeded real catalogue (planted, realistic, the API's ten profiles, mid-week replans).
- `baseline`: an LLM-only planner - Claude given the same problem as JSON, asked for the plan.
- `run`: plans each scenario with a planner and scores it with the solver's validator and
  metrics, never the planner's own claims.
- `report`: evals/REPORT.md with hand-drawn SVG charts.
"""
