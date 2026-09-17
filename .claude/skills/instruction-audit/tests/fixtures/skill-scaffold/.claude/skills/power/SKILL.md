---
name: power
description: Sample-size and power calculations for experiments.
---

# Power analysis

## Overview

Power analysis answers one of the most consequential questions in an experiment: how many units must be observed before a test can detect the effect. Every study should settle it before data collection starts.

## Workflow

- Always check the assumptions of the test before running it.
- Don't test multiple ways until something is significant.
- Verify no unintended circular references remain in the workbook.
- Commit to a visual motif for the deck and keep every chart on it.

## Resources

- `scripts/power.py` — unified closed-form interface; every call must pass alpha, power and the effect size.
- `reference/tables.md` — critical values you should cite in the report.

## Related skills

- `report` for the write-up; it must be run after this one.
