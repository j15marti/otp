#!/usr/bin/env python3
"""Exact Polynomial Calculus degree over GF(2) for small CNFs.

Why PC over GF(2): it contains the "free package" for 3-CNF inputs.
  * Gaussian elimination: a 3-variable XOR written as 4 clauses is the *sum* of
    those 4 clause polynomials (a linear form), so every XOR constraint is
    available at degree 3 and GE is then degree-1 linear algebra.
  * 2-SAT / unit propagation: an implication chain is followed at degree 2;
    any unsatisfiable 2-CNF has a width-2 resolution refutation, which PC
    simulates at degree <= 3.
So "refutable at degree <= 3" is (an upper bound on) what the free package
does for free, and the *residual degree* above 3 is the axis-4 resource:
the dimension of the polynomial space any refuter in this system must use.

Semantics (exact, not heuristic): degree-d PC over GF(2) with Boolean axioms
built in (multilinear arithmetic). V_d is the smallest linear space of
polynomials of degree <= d that contains the clause axioms and is closed
under p -> x*p for p in V_d with deg(p) <= d-1. The CNF is refuted at degree
d iff 1 is in V_d. With columns ordered by degree, any echelon basis has the
property that V_d restricted to degree <= d-1 is spanned by the basis vectors
whose leading monomial has degree <= d-1, so closing over those is exact.

(PC usually allows x*p whenever deg(x*p) <= d, which can only lower the
degree by a small amount; the variant here is the standard one for degree
counting and is monotone in d.)
"""

import argparse
import itertools
import json
import random
import sys
import time
from math import comb


# -- instances ----------------------------------------------------------------
# A CNF is a list of clauses; a clause is a tuple of non-zero ints (DIMACS).

def rand_kcnf(n, m, k, rng):
    cnf = []
    for _ in range(m):
        vs = rng.sample(range(1, n + 1), k)
        cnf.append(tuple(v if rng.random() < 0.5 else -v for v in vs))
    return cnf


def xor_clauses(vs, rhs):
    """CNF for x_vs[0] ^ ... = rhs: forbid every assignment with the wrong parity."""
    out = []
    for signs in itertools.product((0, 1), repeat=len(vs)):
        if sum(signs) % 2 != rhs:
            # forbid this assignment: clause is falsified exactly there
            out.append(tuple(-v if s else v for v, s in zip(vs, signs)))
    return out


def gf2_unsat(rows, n):
    """rows: list of (varlist, rhs). True iff the linear system has no solution."""
    piv = {}
    for vs, b in rows:
        v = 0
        for x in vs:
            v ^= 1 << x
        v = (v << 1) | b          # bit 0 holds the RHS
        while v >> 1:
            p = v.bit_length() - 1
            if p in piv:
                v ^= piv[p]
            else:
                piv[p] = v
                break
        else:
            if v == 1:
                return True
    return False


def rand_3xor(n, m, rng):
    while True:
        rows = [(rng.sample(range(1, n + 1), 3), rng.randrange(2)) for _ in range(m)]
        if gf2_unsat(rows, n):
            return [c for vs, b in rows for c in xor_clauses(vs, b)]


def tseitin_3reg(nv, rng):
    """Tseitin on a random simple 3-regular graph with odd total charge.
    Variables are edges (3*nv/2 of them); always unsatisfiable."""
    assert nv % 2 == 0
    while True:
        stubs = [v for v in range(nv) for _ in range(3)]
        rng.shuffle(stubs)
        edges = [tuple(sorted(stubs[i:i + 2])) for i in range(0, len(stubs), 2)]
        if all(a != b for a, b in edges) and len(set(edges)) == len(edges):
            break
    inc = {v: [] for v in range(nv)}
    for e, (a, b) in enumerate(edges, 1):
        inc[a].append(e)
        inc[b].append(e)
    charge = [0] * nv
    charge[rng.randrange(nv)] = 1
    return [c for v in range(nv) for c in xor_clauses(inc[v], charge[v])], len(edges)


# -- satisfiability (to keep only genuinely UNSAT instances) ------------------

def satisfiable(cnf, n):
    def simplify(cls, lit):
        out = []
        for c in cls:
            if lit in c:
                continue
            if -lit in c:
                c = tuple(l for l in c if l != -lit)
                if not c:
                    return None
            out.append(c)
        return out

    def dpll(cls):
        while True:
            unit = next((c[0] for c in cls if len(c) == 1), None)
            if unit is None:
                break
            cls = simplify(cls, unit)
            if cls is None:
                return False
        if not cls:
            return True
        counts = {}
        for c in cls:
            for l in c:
                counts[abs(l)] = counts.get(abs(l), 0) + 1
        v = max(counts, key=counts.get)
        for lit in (v, -v):
            s = simplify(cls, lit)
            if s is not None and dpll(s):
                return True
        return False

    sys.setrecursionlimit(10000)
    return dpll(list(cnf))


def unsat_instance(gen, n, rng, tries=2000):
    for _ in range(tries):
        cnf = gen()
        if not satisfiable(cnf, n):
            return cnf
    raise RuntimeError("no UNSAT instance found")


# -- PC degree ----------------------------------------------------------------

class Monomials:
    """All multilinear monomials of degree <= d, indexed so higher degree = higher index."""

    def __init__(self, n, d):
        self.n, self.d = n, d
        self.masks, self.deg = [], []
        for k in range(d + 1):
            for vs in itertools.combinations(range(n), k):
                m = 0
                for v in vs:
                    m |= 1 << v
                self.masks.append(m)
                self.deg.append(k)
        self.index = {m: i for i, m in enumerate(self.masks)}
        self._mul = {}

    def mul_table(self, x):
        t = self._mul.get(x)
        if t is None:
            bit = 1 << x
            t = [self.index.get(m | bit, -1) for m in self.masks]
            self._mul[x] = t
        return t

    def clause_poly(self, clause):
        """Polynomial equal to 1 exactly where the clause is false (axiom: it = 0)."""
        terms = {0}                       # monomials as variable bitmasks
        for lit in clause:
            bit = 1 << (abs(lit) - 1)
            # positive literal false when x=0: factor (1 + x); negative: factor x
            factor = (0, bit) if lit > 0 else (bit,)
            new = set()
            for t in terms:
                for f in factor:
                    new ^= {t | f}
            terms = new
        v = 0
        for t in terms:
            v ^= 1 << self.index[t]
        return v


def pc_refutes(cnf, n, d, mons=None):
    """True/False whether degree-d PC over GF(2) refutes cnf, plus dim(V_d)."""
    M = mons if mons and mons.d == d and mons.n == n else Monomials(n, d)
    deg = M.deg
    basis = {}
    queue = []

    def insert(v):
        while v:
            p = v.bit_length() - 1
            b = basis.get(p)
            if b is None:
                basis[p] = v
                if deg[p] <= d - 1:
                    queue.append(v)
                return p == 0             # leading term is the constant 1
            v ^= b
        return False

    for c in cnf:
        if len(c) > d:
            return False, 0
        if insert(M.clause_poly(c)):
            return True, len(basis)
    tables = [M.mul_table(x) for x in range(n)]
    while queue:
        v = queue.pop()
        idxs = []
        w = v
        while w:
            low = w & -w
            idxs.append(low.bit_length() - 1)
            w ^= low
        for t in tables:
            out = 0
            for i in idxs:
                out ^= 1 << t[i]
            if insert(out):
                return True, len(basis)
    return False, len(basis)


def pc_degree(cnf, n, dmax, col_budget=60000):
    """Smallest d <= dmax refuting cnf; None if not found within limits."""
    d0 = max(len(c) for c in cnf)
    dims = {}
    for d in range(d0, dmax + 1):
        cols = sum(comb(n, k) for k in range(d + 1))
        if cols > col_budget:
            return None, dims, "column budget (%d monomials at d=%d)" % (cols, d)
        ok, dim = pc_refutes(cnf, n, d)
        dims[d] = dim
        if ok:
            return d, dims, ""
    return None, dims, "not refuted up to d=%d" % dmax




# -- experiment driver ----------------------------------------------------------

def run(family, sizes, trials, dmax, seed, budget, density):
    rng = random.Random(seed)
    rows = []
    for n_param in sizes:
        for t in range(trials):
            t0 = time.time()
            if family == "rand3":
                n = n_param
                cnf = unsat_instance(lambda: rand_kcnf(n, int(density * n), 3, rng), n, rng)
            elif family == "rand2":
                n = n_param
                cnf = unsat_instance(lambda: rand_kcnf(n, int(density * n), 2, rng), n, rng)
            elif family == "xor3":
                n = n_param
                cnf = rand_3xor(n, n + 2, rng)
            elif family == "tseitin":
                cnf, n = tseitin_3reg(n_param, rng)
            else:
                raise ValueError(family)
            d, dims, note = pc_degree(cnf, n, dmax, budget)
            row = {"family": family, "n": n, "clauses": len(cnf), "trial": t, "pc_degree": d,
                   "dims": dims, "note": note, "seconds": round(time.time() - t0, 2)}
            rows.append(row)
            print(json.dumps(row), flush=True)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("family", choices=["rand3", "rand2", "xor3", "tseitin"])
    ap.add_argument("--sizes", type=int, nargs="+", required=True)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--dmax", type=int, default=7)
    ap.add_argument("--budget", type=int, default=60000, help="max monomials per degree level")
    ap.add_argument("--density", type=float, default=5.0, help="clauses per variable (rand3/rand2)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    run(a.family, a.sizes, a.trials, a.dmax, a.seed, a.budget, a.density)
