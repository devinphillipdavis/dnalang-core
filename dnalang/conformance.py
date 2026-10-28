"""Differential conformance: random dnalang programs, compiled three ways, must agree.

For each generated program the generator also writes down, on its own, the op list
the program means. A program passes when

  * parse + lower succeed and give exactly that op list;
  * its OpenQASM 3 text parses in Qiskit's importer, with the same operation counts
    and the same measurements (qubit -> bit, in order);
  * without measurements, three unitaries agree up to global phase: a NumPy
    reference built from the generator's op list, Qiskit's reading of the emitted
    OpenQASM 3, and Circuit.to_qiskit().

The generator and the NumPy reference share no code with the compiler: each is a
second reading of the language and of the gate definitions, so a disagreement is a
bug in one of them. Zero failures in n programs bounds the failure rate at
1 - 0.05**(1/n) (about 3/n) with 95% confidence.

  python -m dnalang.conformance -n 10000 --seed 0

Needs qiskit and qiskit-qasm3-import.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .lower import lower
from .parser import parse
from .qc_ir import Circuit, Op

# The language as documented (README, docs/LANGUAGE.md), written out independently
# of lexer.GATE_ALIASES and sema.GATE_ARITY.
SPELLINGS = {
    "h": ["h", "helix"], "x": ["x"], "y": ["y"], "z": ["z"], "s": ["s"], "t": ["t"],
    "sx": ["sx"], "rx": ["rx", "splice"], "ry": ["ry", "fold"], "rz": ["rz", "twist"],
    "cx": ["cx", "bond"], "cz": ["cz"], "swap": ["swap"],
}
ROTATIONS = {"rx", "ry", "rz"}
TWO_QUBIT = {"cx", "cz", "swap"}
UNITS = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3}

Expr = Tuple[str, Callable[[Dict[str, float]], float]]   # source text, value in an env


# --- reference semantics ------------------------------------------------------

def _gate_matrix(name: str, params: Tuple[float, ...]) -> np.ndarray:
    """Standard OpenQASM 3 stdgates matrices; for two-qubit gates the first qubit
    listed is the most significant (control first)."""
    r2 = 1 / math.sqrt(2)
    if name in ROTATIONS:
        c, s = math.cos(params[0] / 2), math.sin(params[0] / 2)
        if name == "rx":
            return np.array([[c, -1j * s], [-1j * s, c]])
        if name == "ry":
            return np.array([[c, -s], [s, c]], dtype=complex)
        return np.diag([complex(c, -s), complex(c, s)])
    fixed = {
        "h": [[r2, r2], [r2, -r2]],
        "x": [[0, 1], [1, 0]],
        "y": [[0, -1j], [1j, 0]],
        "z": [[1, 0], [0, -1]],
        "s": [[1, 0], [0, 1j]],
        "t": [[1, 0], [0, complex(r2, r2)]],
        "sx": [[0.5 + 0.5j, 0.5 - 0.5j], [0.5 - 0.5j, 0.5 + 0.5j]],
        "cx": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]],
        "cz": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, -1]],
        "swap": [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]],
    }
    return np.array(fixed[name], dtype=complex)


def reference_unitary(circ: Circuit) -> np.ndarray:
    """Unitary of a measurement-free circuit, in Qiskit's little-endian order
    (qubit 0 is the least significant bit of the basis-state index)."""
    n = circ.n_qubits
    u = np.eye(2 ** n, dtype=complex).reshape([2] * n + [2 ** n])
    for o in circ.ops:
        if o.name in ("barrier", "delay"):
            continue
        if o.name == "measure":
            raise ValueError("reference_unitary needs a circuit without measurements")
        k = len(o.qubits)
        g = _gate_matrix(o.name, o.params).reshape([2] * (2 * k))
        axes = [n - 1 - q for q in o.qubits]
        u = np.moveaxis(np.tensordot(g, u, axes=(list(range(k, 2 * k)), axes)), list(range(k)), axes)
    return u.reshape(2 ** n, 2 ** n)


# --- program generator --------------------------------------------------------

def _literal(rng: random.Random) -> Expr:
    form = rng.randrange(3)
    if form == 0:
        text = str(rng.randint(0, 9))
    elif form == 1:
        text = f"{rng.randint(0, 9)}.{rng.randint(0, 999):03d}"
    else:
        text = f"{rng.randint(1, 9)}.{rng.randint(0, 9)}e-{rng.randint(1, 3)}"
    value = float(text)
    return text, lambda env: value


def _expr(rng: random.Random, params: List[str], depth: int = 0) -> Expr:
    roll = rng.random()
    if depth >= 2 or roll < 0.35:
        choice = rng.randrange(4) if params else rng.randrange(3)
        if choice == 0:
            return _literal(rng)
        if choice == 1:
            fn = rng.choice(["pi", "phi"])
            value = math.pi if fn == "pi" else (1 + 5 ** 0.5) / 2
            return f"{fn}()", lambda env: value
        if choice == 2:
            text, f = _literal(rng)
            return f"sqrt({text})", lambda env: math.sqrt(f(env))
        name = rng.choice(params)
        return name, lambda env: env[name]
    if roll < 0.45:
        text, f = _expr(rng, params, depth + 1)
        return f"-({text})", lambda env: -f(env)
    op = rng.choice("+-*/")
    lt, lf = _expr(rng, params, depth + 1)
    if op == "/":                                   # divide only by a nonzero literal
        rt = str(rng.randint(1, 9)); rv = float(rt)
        return f"({lt}) / {rt}", lambda env: lf(env) / rv
    rt, rf = _expr(rng, params, depth + 1)
    ops = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b}
    fn = ops[op]
    return f"({lt}) {op} ({rt})", lambda env: fn(lf(env), rf(env))


@dataclass
class _Gene:
    name: str
    ports: List[str]
    params: List[str]
    body: List[Tuple[str, ...]] = field(default_factory=list)   # source lines
    meaning: List[Callable] = field(default_factory=list)      # (env, port map, cbit counter) -> [Op]


def _gene(rng: random.Random, index: int, max_ports: int) -> _Gene:
    g = _Gene(f"g{index}", [f"p{i}" for i in range(rng.randint(1, max_ports))],
              [f"a{i}" for i in range(rng.randint(0, 2))])
    for k in range(rng.randint(1, 6)):
        kind = rng.choices(["gate", "wait", "echo", "barrier", "cleave"], [70, 8, 8, 6, 8])[0]
        if kind == "gate":
            names = [n for n in SPELLINGS if len(g.ports) >= (2 if n in TWO_QUBIT else 1)]
            name = rng.choice(names)
            spelling = rng.choice(SPELLINGS[name])
            ports = rng.sample(g.ports, 2 if name in TWO_QUBIT else 1)
            arg = _expr(rng, g.params) if name in ROTATIONS else None
            g.body.append(f"{spelling}{'(' + arg[0] + ')' if arg else ''} {', '.join(ports)};")
            g.meaning.append(lambda env, pm, cb, name=name, ports=ports, arg=arg: [
                Op(name, tuple(pm[p] for p in ports), (arg[1](env),) if arg else ())])
        elif kind == "wait":
            unit = rng.choice(list(UNITS))
            amount = f"{rng.randint(1, 999)}.{rng.randint(0, 9)}"
            ports = rng.sample(g.ports, rng.randint(1, len(g.ports)))
            seconds = float(amount) * UNITS[unit]
            g.body.append(f"wait({amount}{unit}) {', '.join(ports)};")
            g.meaning.append(lambda env, pm, cb, ports=ports, d=seconds: [
                Op("delay", (pm[p],), duration_s=d) for p in ports])
        elif kind == "echo":
            pauli = rng.choice("XY")
            ports = rng.sample(g.ports, rng.randint(1, len(g.ports)))
            g.body.append(f"echo({pauli}) {', '.join(ports)};")
            g.meaning.append(lambda env, pm, cb, ports=ports, p=pauli.lower(): [
                Op(p, (pm[q],)) for q in ports])
        elif kind == "barrier":
            ports = rng.sample(g.ports, rng.randint(1, len(g.ports)))
            g.body.append(f"barrier {', '.join(ports)};")
            g.meaning.append(lambda env, pm, cb, ports=ports: [
                Op("barrier", tuple(pm[p] for p in ports))])
        else:
            port = rng.choice(g.ports)
            g.body.append(f"cleave {port} -> m{k};")
            g.meaning.append(lambda env, pm, cb, port=port: [Op("measure", (pm[port],), cbit=cb())])
    return g


def random_program(seed: int) -> Tuple[str, Circuit]:
    """A valid dnalang program and the circuit it means, derived without the compiler."""
    rng = random.Random(seed)
    width = rng.randint(1, 5)
    genes = [_gene(rng, i, min(3, width)) for i in range(rng.randint(1, 3))]
    lines = [f"// conformance program, seed {seed}", f"organism C{seed} {{"]
    for g in genes:
        sig = ", ".join(f"{p}: angle" for p in g.params)
        lines.append(f"  gene {g.name}({sig}) on {', '.join(g.ports)} {{")
        lines += [f"    {s}" for s in g.body]
        lines.append("  }")
    lines.append("  genome {")
    ops: List[Op] = []
    measured = [0]

    def next_cbit() -> int:
        measured[0] += 1
        return measured[0] - 1

    used = []
    for _ in range(rng.randint(1, 5)):
        g = rng.choice(genes)
        qubits = rng.sample(range(width), len(g.ports))
        args = [_expr(rng, []) for _ in g.params]
        env = {p: a[1]({}) for p, a in zip(g.params, args)}
        arg_text = f"({', '.join(a[0] for a in args)})" if args else "()"
        lines.append(f"    {g.name}{arg_text} @ [{', '.join(map(str, qubits))}];")
        pm = dict(zip(g.ports, qubits))
        for meaning in g.meaning:
            ops += meaning(env, pm, next_cbit)
        ops.append(Op("barrier", tuple(qubits)))     # lower() separates gene instances
        used += qubits
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n", Circuit(1 + max(used), measured[0], ops, f"C{seed}")


# --- checks -------------------------------------------------------------------

def _without_measurements(circ: Circuit) -> Circuit:
    return Circuit(circ.n_qubits, circ.n_cbits, [o for o in circ.ops if o.name != "measure"], circ.name)


def check_circuit(circ: Circuit, atol: float = 1e-10) -> List[str]:
    """Problems with how a compiled circuit is exported (empty list = conformant)."""
    from qiskit import qasm3
    from qiskit.quantum_info import Operator

    problems: List[str] = []
    try:
        parsed = qasm3.loads(circ.to_qasm3())
    except Exception as e:                       # noqa: BLE001 - any rejection is a finding
        return [f"OpenQASM 3 rejected by Qiskit: {type(e).__name__}: {e}"]
    ir_counts = Counter(o.name for o in circ.ops)
    if Counter(dict(parsed.count_ops())) != ir_counts:
        problems.append(f"op counts differ: IR {dict(ir_counts)} vs QASM {dict(parsed.count_ops())}")
    ir_meas = [(o.qubits[0], o.cbit) for o in circ.ops if o.name == "measure"]
    qasm_meas = [(parsed.find_bit(i.qubits[0]).index, parsed.find_bit(i.clbits[0]).index)
                 for i in parsed.data if i.operation.name == "measure"]
    if ir_meas != qasm_meas:
        problems.append(f"measurements differ: IR {ir_meas} vs QASM {qasm_meas}")

    bare = _without_measurements(circ)
    reference = Operator(reference_unitary(bare))
    for label, build in (("OpenQASM 3", lambda: qasm3.loads(bare.to_qasm3())),
                         ("to_qiskit", bare.to_qiskit)):
        try:
            if not Operator(build()).equiv(reference, rtol=0, atol=atol):
                problems.append(f"{label} unitary differs from the reference")
        except Exception as e:                   # noqa: BLE001
            problems.append(f"{label} failed: {type(e).__name__}: {e}")
    return problems


def check_program(source: str, expected: Optional[Circuit] = None) -> List[str]:
    """Problems compiling and exporting a program (empty list = conformant)."""
    try:
        circ = lower(parse(source))
    except Exception as e:                       # noqa: BLE001
        return [f"compile failed: {type(e).__name__}: {e}"]
    problems = []
    if expected is not None:
        if (circ.n_qubits, circ.n_cbits) != (expected.n_qubits, expected.n_cbits):
            problems.append(f"shape: got {circ.n_qubits}q/{circ.n_cbits}c, "
                            f"expected {expected.n_qubits}q/{expected.n_cbits}c")
        if circ.ops != expected.ops:
            first = next((i for i, (a, b) in enumerate(zip(circ.ops, expected.ops)) if a != b),
                         min(len(circ.ops), len(expected.ops)))
            problems.append(f"lowered ops differ from the program's meaning at op {first}")
    return problems + check_circuit(circ)


@dataclass
class Report:
    programs: int
    seed: int
    failures: List[Dict] = field(default_factory=list)

    @property
    def upper_95(self) -> float:
        """One-sided 95% upper bound on the failure rate (exact binomial when zero failed)."""
        if self.failures:
            return float("nan")
        return 1 - 0.05 ** (1 / self.programs)

    def to_dict(self) -> Dict:
        return {"programs": self.programs, "seed": self.seed, "failed": len(self.failures),
                "failure_rate_upper_95": self.upper_95, "failures": self.failures}


def run(programs: int, seed: int = 0) -> Report:
    report = Report(programs, seed)
    for i in range(programs):
        program_seed = seed * 1_000_000 + i
        source, expected = random_program(program_seed)
        problems = check_program(source, expected)
        if problems:
            report.failures.append({"seed": program_seed, "problems": problems, "source": source})
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dnalang.conformance", description=__doc__.split("\n")[0])
    ap.add_argument("-n", "--programs", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    report = run(args.programs, args.seed)
    out = report.to_dict()
    out["failures"] = out["failures"][:5]           # the first few, with their sources
    json.dump(out, sys.stdout, indent=2)
    print()
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
