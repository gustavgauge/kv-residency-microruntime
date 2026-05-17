# Active Prefill Admission Decision

## Question

Can compact resident spans survive if the bulky active prefill is served but not admitted into reusable KV cache?

## Current Interpretation

The prior live negative exposed a missing layer: active prefill materialization competes with resident future-reuse claims. KV residency is both eviction and admission.

## Hard Seed

- Seed: `active-prefill-bulky-admission`
- Cache-all active prefill should break `small_hot` and `small_warm`.
- Disposable or density-gated active prefill should preserve resident value 17.
- Scheduled chunking alone does not bound live KV under full attention.

## Falsifier

Falsified if cache-all active prefill does not break the compact resident thresholds, or if no-cache/density-gated active prefill fails to preserve small_hot and small_warm at threshold value 17.
