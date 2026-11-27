# Algorithms and Data Structures (AD) exams

Exam problem sets from the course **Algoritmer og Datastrukturer** (Algorithms
and Data Structures), course code NDAA04010U, at the University of Copenhagen
(UCPH). The course is taught in Danish.

- `danish/` holds the original problem sets.
- `english/` holds machine translations. They leave out information that is
  specific to one edition of the course, using `\placeholder{...}` instead.

Each folder has a `template.tex` that turns a problem set into a complete
exam PDF, with or without answers. The [main README](../README.md) describes
the templates, the macros, and how to convert a problem set to QTI or WISEflow.

## Problem sets

| File | Exam |
|---|---|
| `ad-problems-trial-2023.tex` | Trial exam, March 2023 |
| `ad-problems-april-2023.tex` | Exam, April 2023 |
| `ad-problems-april-2024.tex` | Exam, April 2024 |
| `ad-problems-june-2024.tex` | Exam, June 2024 |
| `ad-problems-march-2025.tex` | Exam, March 2025 |
| `ad-problems-june-2025.tex` | Exam, June 2025 |
| `ad-problems-april-2026.tex` | Exam, April 2026 |
| `ad-problems-june-2026.tex` | Exam, June 2026 |

Each exam has two parts:

- **Multiple-choice:** 18 questions worth 4% each. The 2023 trial exam has 9.
  Each question says whether it has exactly one correct answer or one or more.
- **Written problems:** 3–4 problems with their weights stated. Each consists
  of subquestions answered in writing: proofs, analyses, algorithms, and hand
  simulations.

## Curriculum

The textbook is Cormen, Leiserson, Rivest and Stein, *Introduction to
Algorithms* (CLRS). The 4th edition is used from 2024 on and the 3rd edition
in 2023; some problems refer to 3rd-edition chapters that are online-only in
the 4th edition. Section numbers below are from the 4th edition.

**Analysis and correctness**
- Asymptotic notation and running-time analysis of iterative and recursive
  algorithms (Ch. 2–3)
- Recurrences: setting them up and solving them with the master theorem,
  recursion trees and substitution (Ch. 4)
- Loop invariants and correctness arguments; proofs by induction
- Divide and conquer, e.g. merge sort and its variants (Section 2.3)
- Lower bounds for comparison sorting (Section 8.1)
- Amortized analysis, including dynamic tables and the potential method
  (Ch. 16)

**Data structures**
- Binary search trees (Ch. 12)
- Red-black trees: invariants, rotations, insertion and running time (Ch. 13)
- Fibonacci heaps (3rd edition Ch. 19, online in the 4th edition)
- Disjoint sets with union by rank and path compression (Ch. 19)
- LSM trees (from a course note, from 2026)
- Choosing a data structure for an application

**Algorithm design**
- Dynamic programming: rod cutting, matrix-chain multiplication, longest
  common subsequence, and new problems in the same style (Ch. 14)
- Greedy algorithms: activity selection, Huffman codes, and exchange arguments
  (Ch. 15)

**Graph algorithms**
- Minimum spanning trees: cuts and safe edges, Kruskal's and Prim's
  algorithms (Ch. 21)
- Single-source shortest paths: Bellman-Ford, Dijkstra, and shortest-path
  trees (Ch. 22)
- Bipartite matching (Ch. 25)

**Other topics**
- Parallel algorithms: work, span, parallelism and greedy scheduling (Ch. 26)
- Computational geometry: convex hulls with Graham's scan, and closest pair of
  points (3rd edition Ch. 33, online in the 4th edition)

## License

Copyright (c) 2026 Mikkel Abrahamsen, Rasmus Pagh, Amir Yehudayoff.
The problems are licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); see [LICENSE](LICENSE).
