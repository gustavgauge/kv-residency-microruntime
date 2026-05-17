# Resident KV Claims MicroRuntime

This repository is a small executable model for resident KV claim semantics. It
does not run models or replace vLLM. It models the ownership layer underneath
prefix caching: claims, capacity, useful-prefix materialization, active live KV,
future-reuse admission, refusal, demotion, expiry, and claim-level telemetry.

The MicroRuntime exists to make one contract testable:

```text
protected resident KV + active live KV <= usable KV memory
```

When protected resident KV and active live KV cannot both fit, the runtime must
make the conflict observable instead of hiding it inside ordinary cache eviction.

## What This Model Covers

- ordered prefix blocks and leading-prefix materialization predicates;
- resident reusable KV claims with useful-footprint thresholds;
- active live KV pressure in the same finite cache pool;
- write no-admit as a future-reuse admission decision, not active memory relief;
- claim acceptance, refusal, demotion, expiry, harm, and post-release loss;
- small online policies and offline oracle checks over the same action space.

Out of scope: model execution, tokenization fidelity beyond block counts, GPU
scheduling, production serving, learned prediction, and latency benchmarking.

## Quick Start

```bash
uv run --with pytest pytest -q
uv run --with pytest --with-editable . python scripts/arbiter_mechanism_report.py
uv run --with pytest --with-editable . python scripts/materialization_report.py
```

The tests are the main artifact. They encode materialization failure, active
live pressure, no-admit separation, and the minimal ResidentClaim lifecycle used
by the vLLM arbiter artifact.

## Repository Layout

```text
src/kvrt/
  contract.py               # ResidentClaim states, decisions, and events
  arbiter.py                # active/resident capacity arbitration
  active_live.py            # active live KV pressure model
  cache.py                  # finite block cache and free-queue behavior
  runtime.py                # prefix-cache ownership loop
  model.py                  # Prefix, Block, Claim, TraceEvent, RuntimeState
  policies/                 # native, value-density, fair-share, oracle
  eval/                     # reports, materialization surfaces, regret
  export/                   # hard-seed export helpers
tests/                      # executable contract and regression traces
scripts/                    # report rendering and seed export
docs/                       # small generated seeds and decisions
```

## Relationship To The vLLM Artifact

This repository is the reference model. The companion arbiter repository carries
the patched vLLM harness, generated traces, conformance suite, and live
scheduler-path evidence. Keep this repo small and portable; put runtime-specific
evidence in the arbiter artifact.

## Development Principle

Do not ask only whether a policy protects blocks. Ask whether it preserves the
materializable future computation object under scarcity, and whether active-side
or resident-side loss is reported at claim granularity.
