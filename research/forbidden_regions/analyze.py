#!/usr/bin/env python3
"""Summarise results/*.jsonl into the markdown tables used in README.md."""

import collections
import glob
import json
import os
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    path = os.path.join(HERE, "results", name + ".jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def by_n(rows):
    g = collections.defaultdict(list)
    for r in rows:
        g[r["n"]].append(r)
    return sorted(g.items())


def degree_table(rows, title, dmax_label="unrefuted"):
    out = ["**%s**" % title, "",
           "| n | clauses | instances | refuted by free package (deg <= 3) | PC degree distribution | median dim V_3 / monomials(<=3) |",
           "|---|---|---|---|---|---|"]
    for n, rs in by_n(rows):
        degs = collections.Counter(r["pc_degree"] for r in rs)
        free = sum(1 for r in rs if r["pc_degree"] is not None and r["pc_degree"] <= 3)
        ratios = sorted(r["dims"].get("3", 0) / sum(comb(n, k) for k in range(4)) for r in rs)
        dist = ", ".join("%s: %d" % (dmax_label if d is None else "deg %d" % d, c)
                         for d, c in sorted(degs.items(), key=lambda kv: (kv[0] is None, kv[0])))
        out.append("| %d | %d | %d | %d/%d | %s | %.3f |" % (
            n, rs[0]["clauses"], len(rs), free, len(rs), dist, ratios[len(ratios) // 2]))
    return "\n".join(out)


def control_table():
    out = ["| family | n (variables) | PC degree over GF(2) (all instances) |", "|---|---|---|"]
    for fam, label in (("tseitin", "Tseitin, random 3-regular graph"), ("xor3", "random 3-XOR (CNF-encoded)"),
                       ("rand2", "random 2-CNF, density 1.5")):
        for n, rs in by_n(load(fam)):
            out.append("| %s | %d | %s |" % (label, n, sorted(set(r["pc_degree"] for r in rs))))
    return "\n".join(out)


def width_table():
    rows = []
    for path in sorted(glob.glob(os.path.join(HERE, "results", "width_*.jsonl"))):
        with open(path) as f:
            rows += [json.loads(line) for line in f if line.strip()]
    if not rows:
        return "(no width runs)"
    out = ["| family | n | resolution width (no GE) | PC_GF(2) degree (with GE) |", "|---|---|---|---|"]
    deg = {(r["family"], r["n"]): r["pc_degree"] for f in ("tseitin", "xor3") for r in load(f)}
    g = collections.defaultdict(list)
    for r in rows:
        g[(r["family"], r["n"])].append(r)
    for (fam, n), rs in sorted(g.items()):
        widths = sorted(set(r["res_width"] if r["res_width"] is not None else ">" + r["note"] for r in rs),
                        key=str)
        out.append("| %s | %d | %s | %s |" % (fam, n, widths, deg.get((fam, n), 3)))
    return "\n".join(out)


if __name__ == "__main__":
    print(degree_table(load("rand3_d5.0"), "Random 3-CNF, density 5.0 (UNSAT instances only)"))
    print()
    print(degree_table(load("rand3_d4.5"), "Random 3-CNF, density 4.5 (UNSAT instances only)"))
    print()
    print(degree_table(load("rand3_free_d5.0"), "Free package only (degree <= 3), larger n, density 5.0",
                       "needs deg > 3"))
    print()
    print(control_table())
    print()
    print(width_table())
