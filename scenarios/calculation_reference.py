"""Independent exact feasibility reference for the calculation joint check.

This module deliberately shares no code with xbrl_local.calculation. It
decides whether equations[i] @ x == 0 with lo <= x <= hi has a rational
solution by enumerating candidate vertices: the feasible set is a bounded
polytope (every variable is box-bounded), so it is nonempty iff some
vertex exists, and a vertex is the unique solution of n independent
active constraints — all equalities plus n - rank(equalities) bound rows.
All arithmetic uses fractions.Fraction; no floating point is involved.
"""
from fractions import Fraction
from itertools import combinations


def _rank(rows, width):
    grid = [list(row) for row in rows]
    rank = 0
    for column in range(width):
        pivot = next((r for r in range(rank, len(grid)) if grid[r][column]), None)
        if pivot is None:
            continue
        grid[rank], grid[pivot] = grid[pivot], grid[rank]
        for r in range(len(grid)):
            if r != rank and grid[r][column]:
                factor = grid[r][column] / grid[rank][column]
                for c in range(column, width):
                    grid[r][c] -= factor * grid[rank][c]
        rank += 1
    return rank


def _solve(rows, rhs, n):
    """Unique solution of an m-by-n system, or None when not uniquely solvable."""
    grid = [list(row) + [value] for row, value in zip(rows, rhs)]
    pivots = []
    for column in range(n):
        r = len(pivots)
        pivot = next((k for k in range(r, len(grid)) if grid[k][column]), None)
        if pivot is None:
            continue
        grid[r], grid[pivot] = grid[pivot], grid[r]
        for k in range(len(grid)):
            if k != r and grid[k][column]:
                factor = grid[k][column] / grid[r][column]
                for c in range(column, n + 1):
                    grid[k][c] -= factor * grid[r][c]
        pivots.append((r, column))
    if len(pivots) < n:
        return None
    if any(grid[k][n] for k in range(len(pivots), len(grid))):
        return None
    point = [None] * n
    for r, column in pivots:
        point[column] = grid[r][n] / grid[r][column]
    return point


def reference_feasible(equations, lo, hi):
    """Whether equations[i] @ x == 0 with lo <= x <= hi is feasible over Q."""
    n = len(lo)
    if any(lower > upper for lower, upper in zip(lo, hi)):
        return False
    equations = [list(row) for row in equations if any(row)]
    if n == 0:
        return True
    bounds = []
    for i in range(n):
        upper = [Fraction(0)] * n
        upper[i] = Fraction(1)
        bounds.append((upper, hi[i]))
        lower = [Fraction(0)] * n
        lower[i] = Fraction(-1)
        bounds.append((lower, -lo[i]))
    need = n - _rank(equations, n)
    for subset in combinations(range(len(bounds)), need):
        rows = [row[:] for row in equations]
        rhs = [Fraction(0)] * len(rows)
        for index in subset:
            row, value = bounds[index]
            rows.append(row[:])
            rhs.append(value)
        point = _solve(rows, rhs, n)
        if point is None:
            continue
        if all(lower <= x <= upper for lower, x, upper in zip(lo, point, hi)):
            return True
    return False
