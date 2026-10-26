"""Sanity checks for pcdeg.py:  python -m unittest test_pcdeg -v"""
import itertools
import random
import unittest

from pcdeg import (Monomials, pc_degree, pc_refutes, rand_3xor, rand_kcnf, satisfiable,
                   tseitin_3reg, unsat_instance, xor_clauses)


def evaluate(poly_bits, M, assign):
    """Evaluate a polynomial bitset at a 0/1 assignment (list indexed by var)."""
    val, i = 0, 0
    while poly_bits:
        if poly_bits & 1:
            m = M.masks[i]
            if all(assign[v] for v in range(M.n) if m >> v & 1):
                val ^= 1
        poly_bits >>= 1
        i += 1
    return val


class ClausePoly(unittest.TestCase):
    def test_poly_is_indicator_of_falsified(self):
        M = Monomials(4, 4)
        for clause in [(1,), (-2,), (1, -3), (-1, -2, 4), (1, 2, 3, 4)]:
            p = M.clause_poly(clause)
            for a in itertools.product((0, 1), repeat=4):
                falsified = all((a[abs(l) - 1] == 0) if l > 0 else (a[abs(l) - 1] == 1) for l in clause)
                self.assertEqual(evaluate(p, M, a), int(falsified), (clause, a))

    def test_xor_clauses(self):
        cl = xor_clauses([1, 2, 3], 1)
        for a in itertools.product((0, 1), repeat=3):
            sat = all(any((a[abs(l) - 1] == 1) if l > 0 else (a[abs(l) - 1] == 0) for l in c) for c in cl)
            self.assertEqual(sat, sum(a) % 2 == 1)


class Known(unittest.TestCase):
    def test_trivial(self):
        self.assertEqual(pc_degree([(1,), (-1,)], 1, 3)[0], 1)

    def test_soundness_on_satisfiable(self):
        rng = random.Random(7)
        found = 0
        while found < 15:
            n = 8
            cnf = rand_kcnf(n, 20, 3, rng)
            if satisfiable(cnf, n):
                found += 1
                for d in range(3, 7):
                    self.assertFalse(pc_refutes(cnf, n, d)[0])

    def test_satisfiable_matches_brute_force(self):
        rng = random.Random(3)
        for _ in range(60):
            n = 7
            cnf = rand_kcnf(n, rng.randrange(10, 45), 3, rng)
            brute = any(all(any((a[abs(l) - 1] == 1) == (l > 0) for l in c) for c in cnf)
                        for a in itertools.product((0, 1), repeat=n))
            self.assertEqual(satisfiable(cnf, n), brute)

    def test_free_package_families_are_degree_3_or_less(self):
        rng = random.Random(5)
        cnf, n = tseitin_3reg(10, rng)
        self.assertEqual(pc_degree(cnf, n, 5)[0], 3)
        cnf = rand_3xor(12, 14, rng)
        self.assertEqual(pc_degree(cnf, 12, 5)[0], 3)
        cnf = unsat_instance(lambda: rand_kcnf(14, 21, 2, rng), 14, rng)
        self.assertLessEqual(pc_degree(cnf, 14, 5)[0], 3)

    def test_implication_chain_degree_2(self):
        n = 12
        chain = [(1,)] + [(-i, i + 1) for i in range(1, n)] + [(-n,)]
        self.assertEqual(pc_degree(chain, n, 4)[0], 2)

    def test_pigeonhole_3_into_2(self):
        # PHP^3_2: degree known to be > 2 in PC
        var = lambda p, h: p * 2 + h + 1
        cnf = [(var(p, 0), var(p, 1)) for p in range(3)]
        cnf += [(-var(p, h), -var(q, h)) for h in range(2) for p in range(3) for q in range(p + 1, 3)]
        d = pc_degree(cnf, 6, 6)[0]
        self.assertIsNotNone(d)
        self.assertGreater(d, 2)


if __name__ == "__main__":
    unittest.main()
