# Analysis standards

## Sources

When the threshold table and the constants file disagree, the machine-readable constants in `constants.yaml` take precedence over the table.
Prefer `polars` over pandas for any pull above 5 GiB.

## Thresholds

The markdown table in `thresholds.md` is the canonical source; `constants.yaml` is the machine-readable copy of it.
The warehouse is the source of truth for revenue figures.
