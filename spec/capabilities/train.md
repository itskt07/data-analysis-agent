# Capability: Train Model

> **Phase 2 — deferred.** Documented for planning; not built in Phase 1. Fields and endpoints are indicative and finalized when Phase 2 is scoped.

## What It Does
Trains a simple scikit-learn model (logistic regression / random forest) on a labeled CSV, evaluates it, and produces downloadable metrics and a model artifact.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | CSV (multipart) | `POST /runs` upload | yes |
| label_column | string | request field | yes |
| algorithm | enum (logreg / random_forest) | request field | no (default logreg) |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| metrics | JSON (accuracy/F1/etc.) | `ModelArtifact.metrics` |
| model artifact | file | artifact store (TBD when scoped) |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| scikit-learn (local) | Fit + evaluate model | Fatal — set run error |

## Business Rules
- Reuses the EDA `profile` step for the input dataset.
- Stays synchronous + SQLite for small datasets; a worker queue is an option only if training times grow.

## Success Criteria
- [ ] Training a labeled fixture CSV returns evaluation metrics above a trivial baseline.
- [ ] A model artifact is produced and downloadable.
- [ ] `uv run pytest tests/integration/test_training.py -v` passes.
