# Evaluation Set — Design Notes

The 5 golden PRDs in `src/eval/golden_prds/` are not random demos. Their
content is **deliberately shaped** so the evaluation set exercises both the
read path (Skill Library hits) and the write path (Distiller proposals
on misses) of the system. This document records the why so future edits
don't accidentally erase the property.

## Why "leave gaps" on purpose?

A real PM-review setting has a **mixed signal distribution**:

- Some defects line up cleanly with the team's accumulated review
  heuristics (the seed Skill Library catches them).
- Other defects fall in the *blind-spot region* — there's a real problem
  in the PRD, the human reviewer would catch it, but no existing skill
  covers it. These are exactly the cases the Distiller is supposed to
  surface as candidate new skills.

If every PRD trips every seed skill, `query(only_misses=True)` returns
empty and the Distiller never has anything to chew on. We'd be testing a
loop that has nothing to learn from. So we deliberately seed the
evaluation set with at least one *recurring blind spot* across multiple
PRDs.

## The chosen blind spot — design / non-happy states

We picked the **design** critic's coverage of "non-happy UI states"
(empty / loading / error / offline) as the recurring blind spot:

- The mock critic always raises the finding "Error states are not
  defined for the primary flow." regardless of PRD content.
- The seed Skill Library has `accessibility-check` and (multi-role)
  `internal-contradiction` as the only design-injected skills.
- If the PRD text contains none of those skills' trigger keywords,
  the retriever returns `[]` for the design critic, the backfill in
  `_shared.run_critic` keeps `skill_id=None`, and the critique lands
  in `query(only_misses=True)` as a candidate cluster member.

## Distribution across the 5 PRDs

| PRD                          | Design-skill trigger words present?   | Design critique skill_id     |
| ---------------------------- | ------------------------------------- | ---------------------------- |
| prd_001_ai_support_widget    | yes (`button`, `form`)                | `accessibility-check` (HIT)  |
| prd_002_loyalty_program      | **none**                              | `None` (MISS)                |
| prd_003_onboarding_redesign  | **none**                              | `None` (MISS)                |
| prd_004_internal_dashboard   | yes (`but`)                           | `internal-contradiction` (HIT) |
| prd_005_payment_retry        | **none**                              | `None` (MISS)                |

Three of five PRDs miss → cluster passes the Distiller's
`min_pattern_frequency=3` admission gate → one candidate skill is
proposed under MockProvider (`non-happy-state-spec`,
`generalization_score=0.77`, evidence pointing back to the three
miss runs).

The two HITs (prd_001, prd_004) prove the system *isn't* just blind on
design wholesale — they retrieve and back-fill correctly when keywords
are present. Without them, the eval set wouldn't test the contrast.

## Trigger words to keep absent from the three "miss" PRDs

If you re-edit `prd_002`, `prd_003`, or `prd_005`, keep these words OUT
to preserve the design-blind-spot property:

- **accessibility-check trigger keywords**: `ui`, `screen`, `button`,
  `modal`, `dialog`, `form`, `color`, `accessibility`, `a11y`, `keyboard`,
  `tooltip`, `icon`.
- **internal-contradiction trigger keywords**: `all users`, `every user`,
  `opt-in`, `opt-out`, `mandatory`, `optional`, `required`, `however`,
  `but`, `except`.

The audit lives in repo history; re-run it with:

```python
import re
from pathlib import Path
KW = ['ui','screen','button','modal','dialog','form','color','accessibility',
      'a11y','keyboard','tooltip','icon','all users','every user','opt-in',
      'opt-out','mandatory','optional','required','however','but','except']
for f in sorted(Path('src/eval/golden_prds').glob('prd_*.md')):
    text = f.read_text(encoding='utf-8').lower()
    hits = [k for k in KW if (' ' in k and k in text) or
            (' ' not in k and re.search(rf'\b{re.escape(k)}\b', text))]
    print(f'{f.name}: {hits}')
```

`prd_002`, `prd_003`, and `prd_005` MUST print empty lists. If a future
edit re-introduces any trigger word in those three files, the Distiller's
design cluster drops below 3 PRDs and the candidate disappears.

## Implications for Day 10 ablation study

When `src/eval/ablation.py` lands, this distribution is the baseline:

- **Skills ON** mode: the design critic finds the issue but no skill
  attribution, supervisor flags it as a P2 finding.
- **Skills OFF** mode: same finding (mock returns the same canned
  critique), no skill block in the prompt, no behavioral difference for
  this particular cluster — but the distinction matters for HIT critics
  (engineering, business) where skill content meaningfully shapes the
  prompt.

The ablation harness must therefore log both per-critic skill-hit rate
and per-critic finding diff, not just an aggregate.

## Adding a new golden PRD

If you add `prd_006`, decide upfront which critic dimension it belongs to:

1. **Library-coverage PRD** — content trips at least one seed-skill keyword
   for every critic. Strengthens the read-path eval.
2. **Blind-spot PRD** — content avoids one critic's seed-skill keywords
   on purpose. Adds a vote toward an existing or new Distiller cluster.
3. **Mixed PRD** — common case in practice.

Update this table when you do, so the design intent stays legible.
