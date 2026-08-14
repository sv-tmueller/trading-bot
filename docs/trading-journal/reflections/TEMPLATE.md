# Weekly reflection YYYY-Www (...)

<!-- Replace the title with the actual ISO week and date range, e.g.:
     # Weekly reflection 2026-W32 (Mon 3 Aug - Fri 7 Aug 2026)
     Written by the weekly-reflection skill
     (.claude/skills/weekly-reflection/SKILL.md); design authority is
     docs/superpowers/specs/2026-08-14-reflection-loop-design.md §2 stage 2. -->

---

## 1. What the week's evidence shows

<!-- Per-trade table for every closed trade this week (date, exit type, nominal vs realized R),
     plus the trailing-20 table carried over verbatim from the latest daily `## Reflection`
     section of the week. Print the sample size next to every number -- never imply it. -->

| Date | Exit type | Nominal R | Realized R |
|------|-----------|-----------|------------|
|      |           |           |            |

<!-- Trailing-20 (n=___): realized R cum, 1.0R/1.5R counterfactual cum, stop-width survival,
     cost vs 5bps model -- carried over from the latest daily digest's `## Reflection` section. -->

<!-- Data-availability rule (design §4): if no daily digest this week has a `## Reflection`
     section yet, replace the tables above with this line and leave every counterfactual column
     `n/a`:
     "Pre-engine week: no `## Reflection` sections in the daily digests yet. Only entries,
     fills, and R-multiples from daily-verification.jsonl and the daily digests are available;
     all counterfactual columns (R-target replay, stop-width survival, cost-vs-5bps) are n/a." -->

---

## 2. Deterministic triggers

<!-- Which of the three v1 triggers (design §3) fired on which days -- read from the trigger
     lines each daily digest's `## Reflection` section prints, never recomputed here. For each
     trigger that fired, a persistent-vs-one-week-noise judgment against the prior week's
     reflection doc, if one exists. -->

<!-- If the week has no `## Reflection` sections: "no trigger data; reflection engine not yet
     wired." -->

---

## 3. Recommendations (ranked)

<!-- Ranked list. Each entry is one of: file new (see the hypothesis-issue format in
     .claude/skills/weekly-reflection/SKILL.md#hypothesis-issue-format) / strengthen existing #N /
     close stale #N / no action -- the expected outcome most weeks. Every entry carries its
     dated evidence lines from section 1 or 2; no bare assertions. -->

1.

<!-- Footer restraints (design doc, not restated in full here): this critique never proposes
     bypassing a pre-registered study, and every recommendation above is an input to the
     operator's weekly-review gate (design §2 stage 3), never a decision made by this doc. -->
