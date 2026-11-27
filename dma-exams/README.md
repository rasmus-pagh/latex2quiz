# Discrete Mathematics and Algorithms (DMA) exams

Exam problem sets from the course **Diskret Matematik og Algoritmer**
(Discrete Mathematics and Algorithms), course code NDAB15008U, at the
University of Copenhagen (UCPH). The course is taught in Danish.

- `danish/` holds the original problem sets.
- `english/` holds machine translations. They leave out information that is
  specific to one edition of the course, using `\placeholder{...}` instead.

Each folder has a `template.tex` that turns a problem set into a complete
exam PDF, with or without answers. The [main README](../README.md) describes
the templates, the macros, and how to convert a problem set to QTI or WISEflow.

Next to each problem set are the files generated from it with `latex2quiz.py`:
`-qti.zip` (QTI 2.1 for Canvas), `-learnosity.json` (WISEflow), and
`-without-answers.pdf` / `-with-answers.pdf` (one question per page).
Regenerate them after changing a problem set.

## Problem sets

| File | Exam |
|---|---|
| `dma-problems-2026-trial.tex` | Trial exam, 2026 |
| `dma-problems-2026-january.tex` | Exam, January 2026 |
| `dma-problems-2026-april.tex` | Re-exam, April 2026 |

Each exam consists of 25 multiple-choice questions worth 4 points each, so a
perfect answer gives 100 points. Each question says whether it has exactly
one correct answer or one or more. There are no written problems.

## Curriculum

The course combines discrete mathematics with an introduction to algorithms
and data structures. The algorithms part follows Cormen, Leiserson, Rivest
and Stein, *Introduction to Algorithms* (CLRS).

**Discrete mathematics**
- Logic: propositions, quantifiers and negating statements
- Sets, functions and relations: reflexive, symmetric, antisymmetric and
  transitive relations
- Integers and modular arithmetic
- Combinatorics: counting sequences, orderings and subsets, binomial
  coefficients, and the pigeonhole principle
- Discrete probability: probabilities, expected value and Markov's inequality
- Sums and matrix computations

**Algorithms and their analysis**
- Pseudocode, the RAM model, and properties of good algorithms
- Asymptotic analysis, recurrences and the master theorem
- Sorting: insertion sort and the other sorting algorithms in the syllabus
- Simple array algorithms, e.g. finding a peak

**Data structures**
- Arrays and linked lists, including linked lists represented in arrays
- Heaps and priority queues: max-heap properties and operations
- Binary search trees, including their representation in arrays
- Hashing, including cuckoo hashing
- Disjoint sets

**Graphs**
- Graph concepts and types of graphs
- Breadth-first search and strongly connected components
- Dijkstra's algorithm for shortest paths
- Kruskal's algorithm for minimum spanning trees

## License

Copyright (c) 2026 Mikkel Abrahamsen, Rasmus Pagh.
The problems are licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); see [LICENSE](LICENSE).
