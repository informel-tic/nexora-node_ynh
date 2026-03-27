# CI quality gates and PR completion policy

This document defines the **minimum quality gates** enforced by CI for every pull request.

## Why this exists

Nexora now treats CI as a delivery contract:

1. every PR must execute the same validation chain as local contributors,
2. documentation quality is checked like code quality,
3. workflow regressions are themselves tested.

This avoids stale docs, broken test collection, and accidental weakening of branch quality checks.

## Workflow covered

- GitHub Actions workflow: `.github/workflows/ci.yml`
- Triggered on:
  - every `pull_request`,
  - pushes to `main`/`master`,
  - manual `workflow_dispatch`.

## Required jobs

### 1) `changes`

Purpose: detect whether the PR/push touches executable code paths and enable a docs-only fast path.

Mechanism:

- `dorny/paths-filter@v3` computes `code_changed` output using repository globs (`src/**`, `apps/**`, `tests/**`, `deploy/**`, `scripts/**`, CI workflow, and dependency manifests).
- `test-collection` and `tests` always report a terminal status:
  - they run their real pytest steps only when `code_changed == true`,
  - otherwise they execute a docs-only fast-path acknowledgement step (`echo ...`) to avoid skipped required checks.

### 2) `test-collection`

Purpose: fail fast when imports, discovery, or pytest collection breaks.

Command:

```bash
PYTHONPATH=src python -m pytest --collect-only -q
```

### 3) `docs-quality`

Purpose: keep documentation navigable and keep CI guarantees explicit.

Commands:

```bash
PYTHONPATH=src python -m pytest tests/test_docs_completeness.py -q
PYTHONPATH=src python -m pytest tests/test_docs_inventory_contract.py -q
PYTHONPATH=src python -m pytest tests/test_repo_split_contract.py -q
PYTHONPATH=src python -m pytest tests/test_docs_obsolescence_contract.py -q
PYTHONPATH=src python -m pytest tests/test_ci_guardrails.py -q
python scripts/docs_obsolescence_audit.py --enforce-removal
```

### 4) `tests`

Purpose: execute the complete automated test suite.

Command:

```bash
PYTHONPATH=src python -m pytest tests/ -v --tb=short --junitxml=dist/ci/junit.xml
python scripts/ci_cost_report.py --junit dist/ci/junit.xml --output dist/ci/cost-report.json
```

The `tests` job is required to depend on `changes`, `test-collection`, and `docs-quality`.

### 5) `vision-final-ready`

Purpose: block merges when final-goal guardrails regress.

Commands:

```bash
PYTHONPATH=src python -m pytest tests/test_docs_completeness.py tests/test_docs_inventory_contract.py tests/test_ci_guardrails.py -q
PYTHONPATH=src python -m pytest tests/test_persistence_backend.py -q
PYTHONPATH=src python scripts/load_test_multitenant.py --tenants 12 --requests 1500 --workers 24 --duration-seconds 45 --max-failures 0 --max-p95-ms 750
```

### 6) `nightly-operator-e2e` workflow

Purpose: run a reproducible operator compatibility matrix (adopt/augment/fresh) every night and publish an artifact.

Commands:

```bash
./scripts/e2e_operator_matrix.sh
```

## Guardrail tests

`tests/test_ci_guardrails.py` enforces the CI contract directly from source control:

- workflow runs on `pull_request`,
- required jobs exist,
- change-detection remains explicit and both code jobs keep step-level gating by `code_changed`,
- docs-only fast-path steps are present so required checks are not skipped on docs-only PRs,
- final test job depends on quality gates,
- docs-quality job checks docs completeness, docs inventory/dependency contract, and CI guardrails.
- docs-quality job checks repo-split/subscriber-public contracts (no control-plane artifacts shipped in subscriber scope).
- docs obsolescence markers are blocked and must be removed before merge.
- a dedicated `vision-final-ready` job depends on all core CI jobs and enforces persistence/load/coherence checks.
- operator-only surface matrix is enforced by behavioral API tests (`tests/test_p8_behavioral.py`).
- CI runtime/cost observability is exported as artifacts (`dist/ci/junit.xml`, `dist/ci/cost-report.json`).

If someone edits CI and breaks one of these constraints, CI fails in a deterministic way.

## Contributor checklist before opening a PR

Run locally from repository root:

```bash
python -m pytest tests/test_ci_guardrails.py -q
python -m pytest tests/test_docs_completeness.py -q
python -m pytest tests/test_docs_inventory_contract.py -q
python -m pytest tests/test_repo_split_contract.py -q
python -m pytest tests/test_docs_obsolescence_contract.py -q
python scripts/docs_obsolescence_audit.py --enforce-removal
python -m pytest -q
```

## Last verification

- Last updated: **2026-03-25**.
- Status: quality gates and runtime-observability contracts are enforced in CI and validated locally before merge.
