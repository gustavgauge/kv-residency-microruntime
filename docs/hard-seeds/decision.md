# MicroRuntime-to-vLLM Hard Seeds

## Question

Does live BlockPool behavior follow abstract protected-block accounting or thresholded contiguous-prefix survival?

## Decision

The materialization-regime suite justifies one narrow direct vLLM hook replay. The MicroRuntime now explains a live-class inversion mechanism: policy rankings can change when value is materialized as useful contiguous prefix survival instead of abstract protected block count.

This is not distributional evidence and does not justify broader policy families, deadlines, trust, adversarial metadata, or large sweeps yet.

## Selected Seeds

| seed | abstract-block expectation | thresholded-contiguous expectation | falsifier |
| --- | --- | --- | --- |
| hard-seed-fair_share_fragmentation | naive_fair_share (13.90) | complete_prefix_fair_share,oracle,value_density (18) | Falsified if live BlockPool replay ranks naive_fair_share with nonzero useful cached-prefix reuse comparable to complete-prefix policies; thresholded survival predicts naive_fair_share collapses. |
| hard-seed-footprint_pressure_density | naive_fair_share (19.56) | oracle,value_density (17) | Falsified if live replay cannot separate compact value-density claims from the bulky footprint under the same pressure, or if complete_prefix_fair_share clearly beats value_density. |
| hard-seed-fairness_tax_density_wins | native,oracle,value_density (38) | native,oracle,value_density (38) | Falsified if live replay does not show the fair-round allocator paying value for the low-value tenant when value_density keeps the two high-value same-tenant prefixes useful. |

## Next Live Replay

Replay these seeds through a direct BlockPool/free-queue ownership hook, or a telemetry-equivalent path that reports leading contiguous cached prefix survival. The first seed to run is `hard-seed-fair_share_fragmentation`.

If live ordering follows thresholded contiguous survival, the MicroRuntime is useful as a policy-design substrate for this mechanism. If live ordering follows abstract protected blocks, or neither exported surface explains the result, stop expanding the MicroRuntime and repair the live materialization model first.
