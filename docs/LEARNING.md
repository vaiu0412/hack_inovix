# Learning from decisions

DEPORT learns which recommendations Branch Admins actually take, and puts those – weighted by how much they
matter – first in the next plans.

## What is logged (`decisions` table)
One row per recommendation, every time the admin decides:

| Decision | When | Learned as |
|---|---|---|
| accepted | the plan is accepted with this recommendation in it | taken (1) |
| skipped | **Skip** on a recommendation card – the plan is rebuilt without it | turned down (0) |
| rejected | the whole plan is rejected (with the reason) | turned down (0) |
| modified | the admin corrected the AI's understanding (Modify) first | logged only |
| replaced | the optimised plan was chosen instead | logged only |
| chosen / not_chosen | the OR-Tools optimised plan itself | logged only (Insights) |

Each row keeps the context as JSON: action type, worst risk of the deliveries it protects, how many, minutes saved,
extra km, medical or not, the disruption's type / severity / duration, rain, and what the model predicted then.

**Skip** re-plans instead of patching: the recommender runs again without that action, so the plan stays
consistent (a skipped backup-vehicle move falls back to a reroute, a skipped reroute to prioritise / notify).
**Undo skips** brings them back; the skips stay in the log.

## The model (`modules/learning.py`)
Logistic regression on 19 features (one-hot action type and cause, risk, deliveries, minutes saved, extra km,
medical, severity, duration, rain), standardised, L2 = 10 (strong – a branch makes few decisions), fitted with
Newton steps in numpy – no extra dependency.

- **Cold start:** until there are 20 learnable decisions with both outcomes, P(accept) is the smoothed acceptance
  rate of the action type: (taken + 1) / (decided + 2) – 50 % with no history (the cards then show no chance).
- **Ranking:** every plan lists its recommendations by **P(accept) × impact**, impact = minutes saved + 10 per
  delivery protected. Each card shows *Likely taken 94%* once there is history behind it.
- **Quality:** the last 20 % of decisions (by time) are held out; accuracy and AUC are shown on Insights. With the
  150-decision demo history: holdout accuracy 0.80, AUC 0.65 – modest, as expected from a few dozen noisy
  human decisions; it improves as real decisions accumulate.
- **Stored** in the `settings` table (survives a demo reset; the decision log is part of the demo data).

## Retraining
- **Insights → Retrain now** (explains what is missing when there isn't enough data).
- **Automatically:** the API checks every hour and retrains once the model is a day old and new decisions came in
  (`LEARNING_SCHEDULER=off` disables it).
- **Cron / nightly:** `python scripts/retrain_acceptance.py` (same database as the app, `DB_PATH`), e.g.
  `0 2 * * *  cd /app && python scripts/retrain_acceptance.py`.

## Insights page (Branch Admin)
Decisions, share taken, plans accepted / rejected, model status · **taken by action type** (bar chart + table view)
· **what the model learned** (the strongest pushes towards accepting and turning down, with holdout metrics) ·
**most changed** (skipped / modified by action type) · recent decisions. Own branch only (the model itself learns from
all branches). Empty branch: **Load sample history (demo)** adds 150 synthetic decisions marked *sample*.

## Limits
- Labels are per plan for accepted / rejected: when a plan is accepted every remaining recommendation counts as
  taken – Skip is what tells the model about single recommendations.
- Sample history is synthetic and marked as such; real decisions replace it over time.
- A linear model can't see interactions (e.g. "backup vehicle *for medical*") unless they are added as features.
