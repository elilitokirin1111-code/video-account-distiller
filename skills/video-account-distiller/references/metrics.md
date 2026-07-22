# Metric rules

## Null-safe rates

Calculate like, comment, share, save, follow, profile, and engagement rates only with known
numerators and positive denominators. Engagement requires all included interaction components to be
known; missing shares or saves do not mean zero.

`completion_efficiency = avg_watch_time_seconds / duration_seconds`.

## Robust score

For each metric within one account's latest video snapshots:

```text
robust_z = (log1p(metric) - median(log1p(metric))) / (1.4826 * MAD)
```

When MAD is zero, known observations receive `0.0` and unknown observations remain `null`. Combine
available z-scores using configured weights and renormalize over available components. Never fill a
missing component with zero.

## Bands

- S: score >= P95
- A: P80 to P95
- B: P40 to P80
- C: P20 to P40
- D: below P20

These are account-local descriptive layers, not guarantees of future performance. Peer viral index
must remain `null` until a reliable same-platform, same-scale peer baseline exists.
