# Forbidden regions beyond time and space

**Question.** Give a GANN the "free package": polynomial-width attention,
random access, exact Gaussian elimination (GE), exact 2-SAT, and
polynomial-depth global attention. Which residual resource is *forced* to grow
on a well-chosen adversarial ensemble?

**Short answer.** Against an *unrestricted* machine, nothing can be proved
without separating P from NP, because the free package already is
polynomial time. Against the *algebraic shadow* of the free package
(Polynomial Calculus over GF(2), which contains GE and 2-SAT at constant degree),
the residual algebraic dimension (axis 4) provably grows linearly on random
3-CNF. Small-n experiments here reproduce the onset of that growth and confirm
that the classic families the free package *should* dissolve (Tseitin, 3-XOR,
2-CNF) stay at constant degree. The most valuable *open* target is axis 5 in the
proof system Res(⊕).

---

## 1. Why a restricted model is unavoidable

Polynomial-depth global attention with polynomial width and random access can
simulate any polynomial-time algorithm, and GE and 2-SAT are themselves in P.
So the free package is P. An unconditional proof that *any* resource must grow
for every GANN solving k-SAT would therefore separate P from NP. Every
demonstrable "forbidden region" must be relative to a restricted model, such as
a proof system, a communication model, or a class of algorithms. The program is
then: choose the weakest restriction that still contains the free package, and
prove growth there.

## 2. The algebraic shadow of the free package

**Model.** Degree-d Polynomial Calculus over GF(2), written PC₂(d). Lines are
multilinear polynomials of degree ≤ d. The system can take GF(2)-linear
combinations, and can multiply a line by a variable when the result has
degree ≤ d. A 3-CNF clause becomes the polynomial that equals 1 exactly where
the clause is false, with the axiom "= 0".

**Proposition 1 (the free package is degree-3 PC₂ on 3-CNF).**
1. *XOR constraints.* A 3-variable XOR given as its 4 clauses is literally the
   sum of those 4 clause polynomials, a linear form. Proof: the multilinear
   representation of a Boolean function is unique, and both sides are the
   indicator of the wrong-parity assignments. So every XOR constraint is
   available at degree 3.
2. *GE.* Once the constraints are linear forms, Gaussian elimination is
   degree-1 linear algebra inside the span. Derived units and equivalences are
   linear forms too.
3. *2-SAT.* An implication x → y is the polynomial x + xy. Unit propagation
   along a chain stays at degree 2, and any unsatisfiable 2-CNF has a width-2
   resolution refutation, which PC simulates at degree ≤ 3.
4. *Interleaving.* GE and 2-SAT steps that feed each other stay inside the same
   degree-≤3 space. For example, GE yields x + y; multiplying by x gives x + xy,
   the implication.

So for 3-CNF inputs, "the free package refutes F" implies PC₂(3) refutes F.
The **residual degree**, the least d > 3 with PC₂(d) refuting F, is a precise
version of axis 4. It is the dimension of the polynomial space that every
certificate built from free-package-style algebra must enter.

**Theorem (known).** Alekhnovich and Razborov (2001; see also Ben-Sasson and
Impagliazzo) proved the following. A random 3-CNF with Δn clauses, Δ a large
enough constant, needs PC degree Ω(n) over *every* field w.h.p., with the
constant depending on Δ. By the Impagliazzo–Pudlák–Sgall size–degree relation,
this gives PC size 2^Ω(n).
**So axis 4 is a forbidden region, already proved:** the ensemble is random
3-CNF, the growth is linear in n, and GE and 2-SAT are free.

## 3. Experiment

`pcdeg.py` computes the exact PC₂ degree. It finds the least d at which the
closure V_d (the smallest space of degree-≤d polynomials containing the
axioms and closed under multiplication by variables) contains 1. It also
records dim V_d. `test_pcdeg.py` checks the calculator:
- clause polynomials are correct on every assignment;
- satisfiable formulas are never refuted, which is soundness;
- the DPLL filter agrees with brute force;
- an implication chain needs degree 2;
- Tseitin, 3-XOR and 2-CNF need degree ≤ 3;
- pigeonhole PHP⁽ⁿ⁺¹⁾ₙ gives degree n+1, consistent with Razborov's n/2+1
  lower bound.

`reswidth.py` computes exact resolution width, which is the free package
*without* GE.

Every random instance is generated with a fixed seed and kept only if a DPLL
solver confirms it is UNSAT.

### Results

**Random 3-CNF, density 5.0 (UNSAT instances only)**

| n | clauses | instances | refuted by free package (deg <= 3) | PC degree distribution | median dim V_3 / monomials(<=3) |
|---|---|---|---|---|---|
| 10 | 50 | 8 | 8/8 | deg 3: 8 | 0.949 |
| 14 | 70 | 8 | 6/8 | deg 3: 6, deg 4: 2 | 0.774 |
| 18 | 90 | 8 | 4/8 | deg 3: 4, deg 4: 4 | 0.853 |
| 22 | 110 | 8 | 1/8 | deg 3: 1, deg 4: 7 | 0.114 |
| 26 | 130 | 8 | 0/8 | deg 4: 8 | 0.075 |
| 30 | 150 | 8 | 0/8 | deg 4: 8 | 0.051 |
| 34 | 170 | 8 | 0/8 | deg 4: 8 | 0.040 |
| 38 | 190 | 8 | 0/8 | deg 4: 8 | 0.028 |

**Random 3-CNF, density 4.5 (UNSAT instances only)**

| n | clauses | instances | refuted by free package (deg <= 3) | PC degree distribution | median dim V_3 / monomials(<=3) |
|---|---|---|---|---|---|
| 10 | 45 | 8 | 8/8 | deg 3: 8 | 0.938 |
| 14 | 63 | 8 | 4/8 | deg 3: 4, deg 4: 4 | 0.923 |
| 18 | 81 | 8 | 2/8 | deg 3: 2, deg 4: 6 | 0.127 |
| 22 | 99 | 8 | 1/8 | deg 3: 1, deg 4: 7 | 0.085 |
| 26 | 117 | 8 | 0/8 | deg 4: 8 | 0.092 |
| 30 | 135 | 8 | 0/8 | deg 4: 8 | 0.042 |
| 34 | 153 | 8 | 0/8 | deg 4: 8 | 0.033 |
| 38 | 171 | 8 | 0/8 | deg 4: 8 | 0.022 |

**Free package only (degree <= 3), larger n, density 5.0**

| n | clauses | instances | refuted by free package (deg <= 3) | PC degree distribution | median dim V_3 / monomials(<=3) |
|---|---|---|---|---|---|
| 20 | 100 | 10 | 1/10 | deg 3: 1, needs deg > 3: 9 | 0.135 |
| 30 | 150 | 10 | 0/10 | needs deg > 3: 10 | 0.063 |
| 40 | 200 | 10 | 0/10 | needs deg > 3: 10 | 0.026 |
| 50 | 250 | 10 | 0/10 | needs deg > 3: 10 | 0.019 |
| 60 | 300 | 10 | 0/10 | needs deg > 3: 10 | 0.011 |
| 70 | 350 | 10 | 0/10 | needs deg > 3: 10 | 0.007 |
| 80 | 400 | 10 | 0/10 | needs deg > 3: 10 | 0.006 |

| family | n (variables) | PC degree over GF(2) (all instances) |
|---|---|---|
| Tseitin, random 3-regular graph | 12 | [3] |
| Tseitin, random 3-regular graph | 18 | [3] |
| Tseitin, random 3-regular graph | 24 | [3] |
| Tseitin, random 3-regular graph | 30 | [3] |
| Tseitin, random 3-regular graph | 36 | [3] |
| Tseitin, random 3-regular graph | 42 | [3] |
| Tseitin, random 3-regular graph | 48 | [3] |
| Tseitin, random 3-regular graph | 54 | [3] |
| Tseitin, random 3-regular graph | 60 | [3] |
| random 3-XOR (CNF-encoded) | 10 | [3] |
| random 3-XOR (CNF-encoded) | 20 | [3] |
| random 3-XOR (CNF-encoded) | 30 | [3] |
| random 3-XOR (CNF-encoded) | 40 | [3] |
| random 3-XOR (CNF-encoded) | 50 | [3] |
| random 3-XOR (CNF-encoded) | 60 | [3] |
| random 2-CNF, density 1.5 | 10 | [2] |
| random 2-CNF, density 1.5 | 20 | [2] |
| random 2-CNF, density 1.5 | 30 | [2] |
| random 2-CNF, density 1.5 | 40 | [2, 3] |
| random 2-CNF, density 1.5 | 50 | [2, 3] |
| random 2-CNF, density 1.5 | 60 | [2] |

| family | n | resolution width (no GE) | PC_GF(2) degree (with GE) |
|---|---|---|---|
| tseitin | 12 | [4] | 3 |

*(Resolution width: only n = 12 completed within the time limit.)*

### What the data does and doesn't show

- **The free package fails w.h.p. very early.** Degree 3 refutes every random
  3-CNF at n = 10, a minority at n = 18–22, and **none of the instances from
  n = 26 to n = 80**. The span it generates falls from about 95% of the
  degree-≤3 polynomials to under 1%, so the free closure barely gets started.
- **The residual degree is forced up, 3 → 4, at n ≈ 14–26,** and stays at 4
  through n = 38. That plateau is expected rather than a contradiction. The
  Ω(n) constant at Δ ≈ 5 is small, so degree 5 should only appear well beyond
  the n this pure-Python calculator can reach (about 40). Linear growth is the
  *theorem*; these experiments only show where it starts.
- **The controls confirm the free package is genuinely free.** Tseitin and
  3-XOR stay at degree 3 at every size up to 60 variables, and 2-CNF stays
  at 2–3. Yet Tseitin needs resolution width 4 already at 12 variables, and
  width Ω(n) on expanders (Ben-Sasson–Wigderson). GE is precisely what
  dissolves it, as intended.
- **Sampling bias.** Keeping only UNSAT instances near the threshold at small n
  over-represents easy instances. This can only make the measured degrees
  *lower*.

## 4. The five axes, in a provable form

| Axis | Precise version | Status with GE + 2-SAT free |
|---|---|---|
| 4. Residual algebraic rank | PC₂ degree | **Proved:** Ω(n) for random 3-CNF (Alekhnovich–Razborov). Illustrated here. |
| 5. Restricted-certificate size | Res(⊕) size, i.e. resolution over parity clauses, which has free GE built in | **Open in general.** Lower bounds are known for tree-like, regular and bounded-depth fragments. A superpolynomial bound for random 3-CNF in full Res(⊕) is the sharpest new target. |
| 1. Synchronization volume | Communication cost of the search problem Search(F∘g) under a fixed variable partition | **Technique available:** query-to-communication lifting (Raz–McKenzie; Göös–Pitassi–Watson; low-discrepancy gadgets such as inner product). The gadget must be non-linear so GE can't undo it. |
| 2. Residual sequential depth | Resolution depth (≥ width), or Horn-SAT depth | Unconditional in proof systems: Ω(n) for random 3-CNF. For general algorithms it's equivalent to NC ≠ P (Horn-SAT is P-complete). |
| 3. Concurrent-access contention | PRAM / memory-hierarchy models | Weakest. Results are architecture-specific and nothing is SAT-specific. |

**For satisfiable instances** (finding a solution rather than certifying
none exists), proof complexity doesn't apply. The comparable results use
algorithm-class restrictions: the overlap-gap property (Gamarnik), and
low-degree hardness for random k-SAT (Bresler–Huang), which covers "low-degree"
algorithms, roughly attention with bounded effective degree.

## 5. Next steps, ranked

1. **Res(⊕) lower bound for random 3-CNF (axis 5).** This would be a genuinely
   new result. Res(⊕) case-splits on parities, which is GE as a proof system.
   A superpolynomial size bound means that no certificate assembled from free
   elimination plus resolution-style branching stays small. It is stronger than
   axis 4, because Res(⊕) is not purely algebraic.
2. **A GE- and 2-SAT-resistant lifting gadget (axis 1).** Compose Tseitin (whose
   query complexity is high) with a gadget g that has no low-degree GF(2)
   structure and no 2-CNF structure, then lift. The result would be a concrete
   lower bound on synchronization volume that the free package provably can't
   compress.
3. **Push the measurement to degree 5.** A sparse GF(2) elimination in C, or a
   degree-truncated Gröbner engine such as msolve or Singular, should reach
   n ≈ 60–100 and show the second step of the staircase.
4. **The search side.** Model attention as a low-degree polynomial map and adapt
   the low-degree hardness argument for random k-SAT near the algorithmic
   threshold.

*References are from memory. Check exact statements and constants before relying
on them.*

## Reproduce

```sh
python -m unittest test_pcdeg -v
python pcdeg.py rand3 --sizes 10 14 18 22 26 30 34 38 --trials 8 --dmax 8 --budget 400000 --density 5.0 --seed 11
python pcdeg.py rand3 --sizes 20 30 40 50 60 70 80 --trials 10 --dmax 3 --budget 2000000 --density 5.0 --seed 31
python pcdeg.py tseitin --sizes 8 12 16 20 24 28 32 36 40 --trials 5 --dmax 5 --seed 13
python reswidth.py tseitin --sizes 8 --trials 2 --wmax 9 --seed 21
python analyze.py          # regenerates the tables above from results/*.jsonl
```
