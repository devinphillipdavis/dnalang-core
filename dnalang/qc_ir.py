"""Flat circuit IR: a list of operations on physical qubits with durations in seconds.

Deliberately small. It converts losslessly to a Qiskit QuantumCircuit and to
OpenQASM 3 text; those are the only two consumers.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

ONE_Q = {"h", "x", "y", "z", "s", "t", "sx", "rx", "ry", "rz"}
TWO_Q = {"cx", "cz", "swap"}


@dataclass
class Op:
    name: str                       # gate name | delay | barrier | measure
    qubits: Tuple[int, ...]
    params: Tuple[float, ...] = ()
    duration_s: Optional[float] = None   # delay only
    cbit: Optional[int] = None           # measure only


@dataclass
class Circuit:
    n_qubits: int
    n_cbits: int
    ops: List[Op] = field(default_factory=list)
    name: str = "circuit"

    # --- introspection ------------------------------------------------------
    def count(self, name: str) -> int:
        return sum(1 for o in self.ops if o.name == name)

    def two_qubit_count(self) -> int:
        return sum(1 for o in self.ops if o.name in TWO_Q)

    def depth(self) -> int:
        level = [0] * self.n_qubits
        d = 0
        for o in self.ops:
            if o.name == "barrier":
                continue
            t = max(level[q] for q in o.qubits) + 1
            for q in o.qubits:
                level[q] = t
            d = max(d, t)
        return d

    def canonical(self) -> str:
        return json.dumps(
            [[o.name, list(o.qubits), [round(p, 12) for p in o.params], o.duration_s, o.cbit] for o in self.ops],
            separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()

    @classmethod
    def from_staggered_schedule(
        cls,
        schedule: Any,
        state_prep: str = "plus",
        measure: bool = True
    ) -> Circuit:
        """Construct a flat Circuit IR representation from a StaggeredDDSchedule."""
        qubits = getattr(schedule, "qubits", [])
        n_qubits = max(qubits) + 1 if qubits else 0
        n_cbits = len(qubits) if measure else 0
        c = cls(n_qubits=n_qubits, n_cbits=n_cbits, name=getattr(schedule, "schedule_id", "staggered_dd"))

        if state_prep == "plus":
            for q in qubits:
                c.ops.append(Op("h", (q,)))
        elif state_prep == "zero":
            pass
        if qubits:
            c.ops.append(Op("barrier", tuple(qubits)))

        num_pulses = getattr(schedule, "num_pulses", 4)
        pulse_names = ["x", "y", "x", "y"] if num_pulses == 4 else ["x", "y", "x", "y", "y", "x", "y", "x"]
        pulse_map = getattr(schedule, "pulse_offsets_ns", {})
        total_delay_us = getattr(schedule, "total_delay_us", 0.0)
        t_total_s = total_delay_us * 1e-6

        for q in qubits:
            offsets_ns = pulse_map.get(q, [])
            last_t_ns = 0.0
            for idx, t_ns in enumerate(offsets_ns):
                delta_s = max(0.0, (t_ns - last_t_ns) * 1e-9)
                if delta_s > 0:
                    c.ops.append(Op("delay", (q,), duration_s=delta_s))
                gate = pulse_names[idx % len(pulse_names)]
                c.ops.append(Op(gate, (q,)))
                last_t_ns = t_ns
            rem_s = max(0.0, t_total_s - last_t_ns * 1e-9)
            if rem_s > 0:
                c.ops.append(Op("delay", (q,), duration_s=rem_s))

        if qubits:
            c.ops.append(Op("barrier", tuple(qubits)))

        if measure:
            if state_prep == "plus":
                for q in qubits:
                    c.ops.append(Op("h", (q,)))
            for idx, q in enumerate(qubits):
                c.ops.append(Op("measure", (q,), cbit=idx))
        return c

    # --- exporters ------------------------------------------------------------
    def to_qiskit(self, dt: Optional[float] = None):
        """Return a qiskit.QuantumCircuit. Delays are emitted in dt if `dt` is given, else in seconds."""
        from qiskit import QuantumCircuit
        qc = QuantumCircuit(self.n_qubits, self.n_cbits, name=self.name)
        for o in self.ops:
            if o.name == "delay":
                if dt is not None:
                    qc.delay(int(round(o.duration_s / dt)), o.qubits[0], unit="dt")
                else:
                    qc.delay(o.duration_s, o.qubits[0], unit="s")
            elif o.name == "barrier":
                qc.barrier(*o.qubits)
            elif o.name == "measure":
                qc.measure(o.qubits[0], o.cbit)
            else:
                getattr(qc, o.name)(*o.params, *o.qubits)
        return qc

    def to_qasm3(self, dt: Optional[float] = None) -> str:
        lines = ["OPENQASM 3.0;", 'include "stdgates.inc";',
                 f"qubit[{self.n_qubits}] q;", f"bit[{self.n_cbits}] c;"]
        for o in self.ops:
            qs = ", ".join(f"q[{i}]" for i in o.qubits)
            if o.name == "delay":
                if dt is not None:
                    lines.append(f"delay[{int(round(o.duration_s / dt))}dt] {qs};")
                else:
                    lines.append(f"delay[{o.duration_s * 1e9:.3f}ns] {qs};")
            elif o.name == "barrier":
                lines.append(f"barrier {qs};")
            elif o.name == "measure":
                lines.append(f"c[{o.cbit}] = measure {qs};")
            elif o.params:
                # repr is the shortest literal that reads back as the same float, so
                # angles survive export exactly (12 significant digits drifted ~4e-10
                # at 760 rad, found by dnalang.conformance)
                if not all(math.isfinite(p) for p in o.params):
                    raise ValueError(f"{o.name} on {qs}: non-finite parameter {o.params}")
                ps = ", ".join(repr(float(p)) for p in o.params)
                lines.append(f"{o.name}({ps}) {qs};")
            else:
                lines.append(f"{o.name} {qs};")
        return "\n".join(lines) + "\n"
