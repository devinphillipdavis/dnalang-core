"""The conformance harness: its reference semantics, and that it passes and catches bugs."""
import math
import re
from pathlib import Path

import numpy as np
import pytest

from dnalang import conformance as C
from dnalang import lower, parse
from dnalang.lower import strip_barriers
from dnalang.qc_ir import Circuit, Op

EX = Path(__file__).parent.parent / "examples"


def _u(n, *ops):
    return C.reference_unitary(Circuit(n, 0, list(ops)))


def test_reference_single_qubit_identities():
    identity = np.eye(2)
    assert np.allclose(_u(1, Op("h", (0,)), Op("h", (0,))), identity)
    assert np.allclose(_u(1, Op("s", (0,)), Op("s", (0,))), _u(1, Op("z", (0,))))
    assert np.allclose(_u(1, Op("t", (0,)), Op("t", (0,))), _u(1, Op("s", (0,))))
    assert np.allclose(_u(1, Op("sx", (0,)), Op("sx", (0,))), _u(1, Op("x", (0,))))
    theta = 0.7
    assert np.allclose(_u(1, Op("rz", (0,), (theta,))),
                       np.diag([np.exp(-0.5j * theta), np.exp(0.5j * theta)]))


def test_reference_is_little_endian_with_control_first():
    # basis index = q0 + 2*q1
    assert _u(2, Op("cx", (0, 1)))[3, 1] == 1        # |q1=0,q0=1> -> |11>
    assert _u(2, Op("cx", (1, 0)))[3, 2] == 1        # |q1=1,q0=0> -> |11>
    assert _u(2, Op("swap", (0, 1)))[2, 1] == 1      # |01> -> |10>
    assert _u(3, Op("x", (2,)))[4, 0] == 1           # x on q2 sets the 4s bit


def test_reference_treats_delay_and_barrier_as_identity_and_refuses_measurement():
    assert np.allclose(_u(1, Op("delay", (0,), duration_s=1e-6), Op("barrier", (0,))), np.eye(2))
    with pytest.raises(ValueError):
        C.reference_unitary(Circuit(1, 1, [Op("measure", (0,), cbit=0)]))


def test_generated_programs_are_deterministic_and_compile_to_their_meaning():
    for seed in range(20):
        source, expected = C.random_program(seed)
        assert C.random_program(seed)[0] == source
        circ = lower(parse(source))
        assert circ.ops == expected.ops
        assert (circ.n_qubits, circ.n_cbits) == (expected.n_qubits, expected.n_cbits)


def test_failure_rate_bound():
    assert C.Report(3000, 0).upper_95 == pytest.approx(1 - 0.05 ** (1 / 3000))
    assert C.Report(3000, 0).upper_95 < 3 / 3000


def test_random_programs_conform():
    pytest.importorskip("qiskit_qasm3_import")
    report = C.run(300, seed=0)
    assert not report.failures, report.failures[0]


@pytest.mark.parametrize("path", sorted(EX.glob("*.dna")), ids=lambda p: p.name)
def test_examples_conform(path):
    pytest.importorskip("qiskit_qasm3_import")
    circ = lower(parse(path.read_text()))
    assert C.check_circuit(circ) == []
    assert C.check_circuit(strip_barriers(circ)) == []


def test_harness_catches_an_emitter_that_reverses_cx(monkeypatch):
    pytest.importorskip("qiskit_qasm3_import")
    emit = Circuit.to_qasm3
    monkeypatch.setattr(Circuit, "to_qasm3", lambda self, dt=None: re.sub(
        r"cx q\[(\d+)\], q\[(\d+)\]", r"cx q[\2], q[\1]", emit(self, dt)))
    report = C.run(100, seed=7)
    assert report.failures
    assert all("unitary differs" in " ".join(f["problems"]) for f in report.failures)


def test_harness_catches_an_emitter_that_rounds_angles(monkeypatch):
    pytest.importorskip("qiskit_qasm3_import")
    emit = Circuit.to_qasm3
    monkeypatch.setattr(Circuit, "to_qasm3", lambda self, dt=None: re.sub(
        r"\(([-0-9.e]+)\)", lambda m: f"({float(m.group(1)):.3g})", emit(self, dt)))
    assert C.run(100, seed=7).failures


def test_harness_catches_lowering_that_drops_a_gate(monkeypatch):
    real_lower = C.lower

    def lossy(org, **kw):
        circ = real_lower(org, **kw)
        circ.ops = [o for o in circ.ops if o.name != "y"]
        return circ

    monkeypatch.setattr(C, "lower", lossy)
    monkeypatch.setattr(C, "check_circuit", lambda circ, atol=1e-10: [])   # isolate the oracle
    report = C.run(100, seed=7)
    assert report.failures
    assert all("differ from the program's meaning" in f["problems"][0] for f in report.failures)


@pytest.mark.parametrize("angle", [math.pi / 7, -759.4123456789012, 1e-5, 3.0])
def test_angles_survive_export_exactly(angle):
    pytest.importorskip("qiskit_qasm3_import")
    from qiskit import qasm3
    circ = Circuit(1, 0, [Op("rz", (0,), (angle,))])
    assert float(qasm3.loads(circ.to_qasm3()).data[0].operation.params[0]) == angle


def test_non_finite_angles_are_refused_at_export():
    with pytest.raises(ValueError):
        Circuit(1, 0, [Op("rz", (0,), (math.inf,))]).to_qasm3()


def test_large_angle_program_found_by_the_harness_conforms():
    # seed 1000640 failed before angles were exported exactly: 12 significant
    # digits lost ~4e-10 rad at ~139 rad, beyond the 1e-10 unitary tolerance
    pytest.importorskip("qiskit_qasm3_import")
    assert C.check_program(*C.random_program(1000640)) == []
