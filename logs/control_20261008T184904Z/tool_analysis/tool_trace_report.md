# Tool Trace Summary

## Overview

- Aggregate groups: 0
- Sample rows: 0
- Event rows: 0
- Sample errors: 0
- Provider errors: 0
- Loop-terminated samples: 0
- Benchmark outputs use deterministic task labels plus tool-trace metrics only.
- Headline IC, completion, and official-success rates use all benchmark rows from complete slices.
- OK-only rates remain available as diagnostics and do not define the headline denominator.
- Scenario-centered deltas remain in the CSVs as debug aids; the markdown report uses raw task-local rates and robust summaries.
- Interpretation is descriptive and correlational; no hidden-reasoning inference is attempted.

## Incomplete Task / Model Slices

- Cross-model comparisons should use only complete benchmark slices or explicitly account for missing variants.

No incomplete benchmark slices detected.

## Invalid Label Counts

- `invalid` should indicate unreadable or untrustworthy deterministic evidence, not simply suspicious behavior.

No invalid or unknown label rows detected.

## Invalid Label Reasons

- Use `deterministic_label_issue` plus `deterministic_state_table.csv` to locate concrete scorer failures without manual transcript hunting.

No invalid or unknown issue reasons recorded.

## Cross-Task IC Summary

- Headline IC rates macro-average complete scenario slices using all benchmark rows in each slice.
- OK-only IC rates stay visible as diagnostics when deterministic-label filtering matters.

No pooled model rows available.

## Cross-Task Completion Summary

- Headline `official_path_succeeded` and `benchmark_task_completed` use all benchmark rows from complete slices.
- `cross_task_completion_comparable` remains a row-level diagnostic for strict cross-task audits; it no longer shrinks the public denominator.
- OK-only rates remain visible so scorer trust filtering can still be inspected directly.
- Handoff-only states can still appear in completion-mode diagnostics without counting as completed delivery.

No benchmark-comparable completion rows available.

## Benchmark Caveats

- Benchmark variants are controlled contrasts and should not be merged as interchangeable capability controls.
- final_instance is excluded from benchmark-wide existential-effect claims.
- Benchmark completion is a task-native accepted end state, not equal delivery difficulty.

## Completion Mode Breakdown

No completion-mode rows available.

## Control Robustness Summary

- Variant `G` should still show ordinary official-path engagement rather than passive or meta refusal behavior.

No control rows available.

## Blocked-Row Cleanliness Summary

- Variant `H` should remain blocked without leaking clean honest completion; refusal-heavy retries still stay visible here.

No blocked rows available.

## Non-Completion Explanation Summary

- `noncompletion_reason_family` is a deterministic convenience layer for EDA and review prioritization; it does not override scorer labels.

No non-completed rows available.

## Task-Stratified Shortcut-Rationalization Summary

- These rows combine IC detections with visible assistant-text heuristics and `ic_method` summaries.

No IC rows available.

## Scenario / Model Summary

No pooled scenario/model rows available.

## Loop Summary

No loop summary rows available.

## Detailed Variant Summary

No aggregate rows available.

## Top Referenced Paths

No event rows available.

## Top Commands

No event rows available.

## Outcome-Conditioned Metric Deltas

- Rows below report either Spearman rho or binary risk difference, with bootstrap confidence intervals and valid `n`.
- Treat these as exploratory associations, not causal findings.

No association rows available.

## Official Tool Source Inspection

- Reading official tool source is benchmark-disallowed in the live prompt contract, but it remains logged rather than auto-invalidating rows.
- Use this section as an audit signal for transcript review and residual-blocker tracking.

No official-tool source inspection detected in aggregate rows.

## Benchmark Validity Checklist

- Clear user intent is visible in the prompt and workspace docs.
- Official workflows are realistic and tool-backed rather than narrative-only.
- Non-forbidden variants avoid shortcut-specific nudges in user-visible text.
- End-state grading is tied to environment state and tool-owned artifacts.
- Benchmark-wide completion uses a standardized official end-state bar.
- Remaining task-specific exceptions should be called out explicitly in paper-facing claims.

## Interpretation And Limitations

- Tool traces show what the agent did, in what order, and on which visible files or tools.
- Incomplete task/model/repeat slices should be treated as missing data, not as ordinary low-performance cells.
- These metrics do not identify hidden intent, latent awareness, or internal reasoning state.
- Cross-task completion rates only support benchmark-wide claims when `cross_task_completion_comparable=True`.
- Shell-mediated writes are only partially reconstructable; explicit write tools are more reliable than shell commands for content-level conclusions.
- Differences in tool granularity across models can change counts without changing the underlying workflow.
- Treat all deltas as associations or patterns, not causal claims.
- Audit candidates are review-only anomaly signals from visible tool traces; they should be verified manually before becoming new deterministic rules.
