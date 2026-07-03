# Capabilities Index

> **Boilerplate status:** The spec-writer sub-agent creates one file per capability in this directory. Each file describes exactly one discrete thing the agent can do.

---

## What Is a Capability?

A capability is a single, discrete action the agent performs.

## Capabilities in This Project

| Capability | File | Phase |
|-----------|------|-------|
| Profile dataset (EDA + report) | [profile.md](profile.md) | 1 |
| Train model | [train.md](train.md) | 2 |
| Schedule EDA runs & delivery | [schedule.md](schedule.md) | 3 |

> Report rendering is part of the Phase 1 `profile` capability (the EDA run produces the self-contained HTML report), so it is not a separate capability file. The Phase 3 `schedule` capability reuses that same EDA pipeline on a timer — it adds no new agent graph.

## How to Add a New Capability

Create a new `<name>.md` in this directory describing inputs, outputs, side-effects, and tests. Optionally run `/zero-shot-build` to scaffold it.

## Capability File Template

Each capability file should answer:
- **What it does** (one sentence)
- **Inputs** (what data it receives)
- **Outputs** (what it produces)
- **External calls** (APIs, LLMs, databases it touches)
- **Error cases** (what can go wrong and how it's handled)
- **Success criteria** (how we test it)

