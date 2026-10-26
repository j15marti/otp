#!/usr/bin/env python3
"""Exact resolution width for small CNFs: the free package *minus* Gaussian elimination.

Width-w resolution keeps only clauses with <= w literals. Unit propagation and
2-SAT live at width <= 2, so this is "attention + 2-SAT closure" without GE.
The CNF is refuted at width w iff the empty clause is derivable using only
clauses of width <= w (inputs must themselves have width <= w).

Comparing this with pcdeg.py isolates what GE buys: Tseitin formulas on
expanders need resolution width that grows with n (Ben-Sasson-Wigderson),
but PC over GF(2) refutes them at degree 3 because their constraints are linear.
"""

import argparse
import json
import random
import time

from pcdeg import rand_3xor, rand_kcnf, tseitin_3reg, unsat_instance


def refutes_at_width(cnf, w, max_clauses=3_000_000):
    """Saturate under width-bounded resolution. Returns True/False/None (budget)."""
    if any(len(c) > w for c in cnf):
        return False
    known = set()
    by_lit = {}
    frontier = []
    for c in cnf:
        fc = frozenset(c)
        if fc not in known:
            known.add(fc)
            frontier.append(fc)
            for lit in fc:
                by_lit.setdefault(lit, []).append(fc)
    while frontier:
        new = []
        for c in frontier:
            for lit in c:
                for d in list(by_lit.get(-lit, ())):
                    r = (c - {lit}) | (d - {-lit})
                    if len(r) > w or any(-l in r for l in r):
                        continue
                    if not r:
                        return True
                    if r not in known:
                        known.add(r)
                        new.append(r)
                        for l in r:
                            by_lit.setdefault(l, []).append(r)
            if len(known) > max_clauses:
                return None
        frontier = new
    return False


def res_width(cnf, wmax, max_clauses):
    for w in range(max(len(c) for c in cnf), wmax + 1):
        r = refutes_at_width(cnf, w, max_clauses)
        if r is None:
            return None, "clause budget at w=%d" % w
        if r:
            return w, ""
    return None, "not refuted up to w=%d" % wmax


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("family", choices=["rand3", "xor3", "tseitin"])
    ap.add_argument("--sizes", type=int, nargs="+", required=True)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--wmax", type=int, default=10)
    ap.add_argument("--max-clauses", type=int, default=3_000_000)
    ap.add_argument("--density", type=float, default=5.0)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    for size in a.sizes:
        for t in range(a.trials):
            t0 = time.time()
            if a.family == "tseitin":
                cnf, n = tseitin_3reg(size, rng)
            elif a.family == "xor3":
                n, cnf = size, rand_3xor(size, size + 2, rng)
            else:
                n = size
                cnf = unsat_instance(lambda: rand_kcnf(n, int(a.density * n), 3, rng), n, rng)
            w, note = res_width(cnf, a.wmax, a.max_clauses)
            print(json.dumps({"family": a.family, "n": n, "clauses": len(cnf), "trial": t,
                              "res_width": w, "note": note, "seconds": round(time.time() - t0, 2)}),
                  flush=True)
