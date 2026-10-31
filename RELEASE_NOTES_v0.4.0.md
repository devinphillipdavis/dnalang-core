# dnalang-core v0.4.0: Differential Conformance, Symbolic Invariance & Reproducibility Layer

**Release Date:** October 31, 2026  
**Author:** Devin Phillip Davis  
**Affiliation:** Agile Defense Systems LLC / OSIRIS Sovereign Architecture Project  
**Repository:** [osiris-dnalang/dnalang-core](https://github.com/osiris-dnalang/dnalang-core)  
**Concept DOI:** [10.5281/zenodo.23254242](https://doi.org/10.5281/zenodo.23254242)  
**Governance Invariant:** SYS-021 (Payload-Bound Grants) & Gate 0 Portable Substrate Conformance  

---

## 1. Executive Summary

`dnalang-core v0.4.0` establishes formal reproducibility and mathematical conformance guarantees for quantum circuit family representations and evolutionary genetic algorithm search loops. This release introduces:
1. **OpenQASM 3 Differential Conformance Harness** (`dnalang.conformance`): Continuous differential verification ensuring compiled `Circuit` representations exactly match formal OpenQASM 3 operational semantics.
2. **Exact Angle Export**: IEEE-754 precision preservation without lossy float string conversions during quantum transpilation.
3. **Symbolic Invariance Auditing** (`dnalang check --invariance`): Deterministic validation of parameter boundaries, barrier semantics, and Clifford/non-Clifford gate transformations.
4. **Reproducibility Layer Ratification**: Signed ledger records, tamper-evident lineage tracking, and failing fixtures as done-when tests.

---

## 2. Key Enhancements & Technical Innovations

### A. OpenQASM 3 Differential Conformance Engine
* Added `dnalang.conformance` differential testing harness comparing `dnalang` lowering against Qiskit reference execution.
* Ensures little-endian qubit ordering, control-first multi-qubit gate conventions, and identity barrier preservation.
* Fail-closed rejection of non-finite angles (`NaN`, `Inf`) at export boundaries.

### B. Symbolic Invariance Verification
* CLI entry point `dnalang check --invariance` verifies that syntactic transformations preserve target unitary operations under all parameter assignments.
* Hardens gate-level checks across circuit genes, classifier rule sets, and gene regulatory networks (GRNs).

### C. Gate 0 Substrate Portability
* Dynamically resolves all filesystem operations relative to `REPO_ROOT` via `Path(__file__).resolve().parent`.
* Verified multi-node execution on Node Alpha (operator workstation) and Node Beta (Linux WSL / x86_64).

---

## 3. Verification & Test Metrics

* **Test Suite**: 43 passed, 12 skipped, 0 failed in 10.89s under Python 3.12 (`pytest-9.1.1`).
* **Deterministic Lineage Verification**: Every genetic evaluation is cryptographically recorded in Merkle-anchored run ledgers (`tests/test_lineage.py`).
