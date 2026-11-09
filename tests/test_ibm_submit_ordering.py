"""The write-ahead guarantee in dnalang.backends.ibm.submit.

The 'submit-intent' row must be durable on disk before the sampler is called,
and a submission that fails must leave that row behind with no 'submitted' row.
No network or IBM credentials are used: the service, transpiler and sampler
are replaced with fakes.
"""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("qiskit_ibm_runtime")

import dnalang.backends.ibm as ibm  # noqa: E402
from dnalang import Ledger  # noqa: E402
from dnalang.qc_ir import Circuit, Op  # noqa: E402


class _FakeBackend:
    name = "fake_backend"


class _FakeService:
    def backend(self, name):
        return _FakeBackend()


class _FakeJob:
    def job_id(self):
        return "job-123"


def _circuit():
    return Circuit(1, 0, [Op("h", (0,))])


@pytest.fixture
def fake_ibm(monkeypatch):
    """Replace everything that touches IBM or qiskit transpilation."""
    monkeypatch.setattr(ibm, "service", lambda: _FakeService())
    monkeypatch.setattr(ibm, "calibration_hash", lambda backend: "cal-hash")
    monkeypatch.setattr(ibm, "transpile_fixed",
                        lambda circuits, backend, layout, optimization_level=0:
                        [SimpleNamespace(data=[]) for _ in circuits])
    return monkeypatch


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_intent_is_durable_before_sampler_runs(tmp_path, fake_ibm):
    import qiskit_ibm_runtime

    path = tmp_path / "runs.jsonl"
    ledger = Ledger(path)
    seen_before_run = {}

    class _RecordingSampler:
        def __init__(self, mode):
            pass

        def run(self, tqcs, shots):
            # Read the file from disk, not the in-memory ledger, to prove durability.
            seen_before_run["rows"] = _rows(path)
            return _FakeJob()

    fake_ibm.setattr(qiskit_ibm_runtime, "SamplerV2", _RecordingSampler)

    job_id = ibm.submit([_circuit()], "fake_backend", layout=[0], shots=128, ledger=ledger)

    assert job_id == "job-123"
    assert [r["kind"] for r in seen_before_run["rows"]] == ["submit-intent"]
    final = _rows(path)
    assert [r["kind"] for r in final] == ["submit-intent", "submitted"]
    assert final[1]["intent_hash"] == final[0]["hash"]
    assert final[1]["job_id"] == "job-123"
    assert ledger.verify() is None


def test_failed_submission_keeps_intent_and_writes_no_submitted_row(tmp_path, fake_ibm):
    import qiskit_ibm_runtime

    path = tmp_path / "runs.jsonl"
    ledger = Ledger(path)

    class _FailingSampler:
        def __init__(self, mode):
            pass

        def run(self, tqcs, shots):
            raise RuntimeError("provider rejected job")

    fake_ibm.setattr(qiskit_ibm_runtime, "SamplerV2", _FailingSampler)

    with pytest.raises(RuntimeError, match="provider rejected job"):
        ibm.submit([_circuit()], "fake_backend", layout=[0], shots=128, ledger=ledger)

    rows = _rows(path)
    assert [r["kind"] for r in rows] == ["submit-intent"]
    assert rows[0]["shots"] == 128
    assert ledger.verify() is None
