# Stratified sampling

Run sampling only after `metrics` has produced account-local `DerivedMetrics`. The deterministic
strategy prioritizes these observable strata:

1. Promotion/ad and Robust Z-score outliers.
2. Every available S/A/B/C/D performance band.
3. Major `content_type` values as a temporary content-pillar proxy.
4. Short, medium, long, and unknown duration buckets.
5. Recent videos.
6. Balanced round-robin fill across performance bands.

Default size follows account population: all videos below 30; 20–40 for 30–100; 40–80 for
101–500; and 60–120 above 500. An explicit `--size` is capped at the population.

Read `population_coverage`, `selected_coverage`, every video's `selection_reasons`, and warnings.
Never silently claim coverage when a major pillar or available performance band is absent. Small
samples remain useful for description but not strong rules.

The same inputs, config, size, and selected IDs produce the same `smp_*` identifier and reuse the
existing manifest. Sampling does not read raw CSV files.
