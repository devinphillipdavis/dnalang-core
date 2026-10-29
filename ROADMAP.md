# dnalang roadmap

Status: **proposal**, 2026-10-28. The direction was chosen by the maintainer on 2026-10-28; the milestones below are proposals for review.

## Position

dnalang is to be **the reproducibility layer for quantum experiments**. It runs on existing toolkits rather than replacing them.

- **What it is not.** It is not a replacement for Qiskit, PennyLane, Amazon Braket or D-Wave's Ocean. Those provide compilers, simulators and hardware access, built by large teams. dnalang compiles *to* them.
- **What it is.** It makes an experiment checkable after the fact, whichever toolkit ran it:
  - what was planned, frozen and timestamped before any job ran;
  - what was sent, recorded in a hash-chained ledger *before* submission;
  - what came back;
  - whether the effect could exist at all (symbolic invariance audit) and whether it also appears without noise (noiseless baseline).
- **Why this can compete.** As far as we know, none of the large toolkits has a built-in way to freeze an experiment's plan before it runs, or to record each submission before it is sent. Without these, a hardware claim is hard to audit. Each piece already exists somewhere in this project (see the next section), but mostly as one-off code inside individual experiments.

## What exists today

As found in the repositories on 2026-10-28.

| capability | where | state |
|---|---|---|
| Circuit-family language → flat IR → Qiskit or OpenQASM 3 | dnalang-core (`parser`, `sema`, `lower`, `qc_ir`, `backends/qasm3`) | version 0.3.0; not on PyPI |
| Simulation | dnalang-core `backends/aer` (Qiskit Aer) | works |
| Hardware | dnalang-core `backends/ibm`: IBM Quantum, fixed layout | IBM only |
| Hash-chained ledger; `dnalang verify-ledger` | dnalang-core `ledger.py` | works; the IBM backend writes an entry before each submission, and the evolutionary search records lineage. Rows are not signed yet |
| Invariance audit (`dnalang check --invariance`, SymPy) | dnalang-core `invariance.py` | merged 2026-10-28 (PR #4) |
| Evolutionary search with measured fitness | dnalang-core `evolve/` | works |
| Drift checks on job-to-job telemetry | osiris-governance `telemetry.py` | separate package |
| Statistical gate, evidence recomputation, Ed25519 signing | osiris-governance `stat_gate.py`, `evidence_verifier.py`, `signing.py` | separate package |
| Retrospective attestation of finished runs: a manifest of hashes, an Ed25519 signature, re-verification | bridge `attest.py` | works; the E2–E4 manifest awaits a signature from an enrolled key |
| Pre-registration frozen by hash and OpenTimestamps | done by hand per experiment (bridge `results/drift_checks/`) | no tool |
| Noiseless-baseline comparison | done per experiment in bridge | no general tool |
| PennyLane, Braket, D-Wave | — | none |

dnalang-core itself is about 2,100 lines of Python with 36 tests.

## Milestones

### M1: a real package

- Require CI to pass on `main`. The CI pull requests were merged on 2026-10-28.
- Publish `dnalang` on PyPI (the name was free on 2026-10-28), using trusted publishing from GitHub Actions.
- A documentation site (MkDocs on GitHub Pages) with a tutorial, a language reference and an API reference.
- **Signed records.** Every new run's ledger is signed with an enrolled node key. Earlier unsigned runs get retrospective attestations, labeled as such: a signature made later shows that the key holder vouched for the files then, not that they were signed when the jobs ran.
- **Verification fixtures.** A published example run, plus copies of it that must fail verification: a changed file, a truncated ledger, a manifest signed by the wrong key.
- A versioning policy, a CHANGELOG, and a Zenodo DOI for each release. Today's DOI covers a 2026-09-20 snapshot of three repositories (concept DOI 10.5281/zenodo.22862566).

**Done when** `pip install dnalang` works on Python 3.10–3.12, the docs are live, `main` is protected by CI, and someone outside the project installs the release, verifies the genuine example and rejects the altered copies without help. Publishing on PyPI alone shows only that the package installs.

### M2: the reproducibility core

- **`dnalang prereg`.** Freeze a plan: record its SHA-256, stamp it with OpenTimestamps, and pin the code hashes. Runs refuse to start if any of these changed. This turns what the drift-check experiments E4 and E5 (in bridge) did by hand into one command.
- **A ledger for every backend.** Write-ahead entries for every submission, not only IBM's.
- **`dnalang check --baseline`.** Run the same program noiselessly and report whether a claimed effect appears there too.
- **Drift checks.** Either as an extra (`dnalang[drift]`) or through a published osiris-governance. This is a design decision (see below).

**Done when** one worked example runs end to end on Aer and on IBM: plan → freeze → run → verify the ledger → report. Then someone outside the project reproduces one complete run from its plan and ledger, in their own environment, and the discrepancies they find are published. A simulated run is enough for this test; it should not spend QPU time.

### M3: beyond Qiskit

- **PennyLane.** Compile dnalang's IR to a PennyLane tape, giving access to PennyLane's devices and automatic differentiation.
- **Braket and others** through OpenQASM 3, which dnalang already emits.
- **D-Wave: a design study only.** Annealing solves optimization problems (QUBO/BQM), not gate circuits. dnalang would first need a construct for such problems, so this is a question, not a commitment.
- Pre-registration and the ledger apply on every backend.

### M4: evidence that it works

- Pre-registered benchmarks. Examples:
  - Do the invariance audit and the noiseless gate catch seeded defects, without rejecting sound experiments?
  - What does ledger-first submission cost in time?
  - Can a published experiment be reproduced from its plan and its ledger?
- Results are reported whatever they show, negative results included.

## Open decisions

- **Package layout.** dnalang could depend on osiris-governance (published too). Or it could absorb the general reproducibility parts (drift checks, signing, the statistical gate) into a `dnalang.repro` module, leaving OSIRIS-specific governance outside. The second makes `pip install dnalang` self-contained.
- **A home independent of one login.** The repositories are on a personal account. A free GitHub organization would give them a stable home. The organization name `dnalang` is taken (an unrelated organization from 2018), so another name is needed.
- **License.** Apache-2.0 today, which suits the direction.
