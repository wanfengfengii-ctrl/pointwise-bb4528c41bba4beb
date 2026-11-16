"""Exact joint feasibility of declared-precision facts and calculation relations.

Correctness invariants (shared variables, duplicate facts, verify-to-commit):

1. Shared truth values. Every stored or candidate fact of a calculation
   metric contributes exactly one rational variable per economic aspect
   (entity scheme+identifier, period, raw segment/scenario explicit
   dimension maps, expanded unit; never context or fact IDs, never
   default-filled dimensions). All facts of the same metric in the same
   aspect constrain the same variable, and equations from every role share
   that variable, so two batches that each pass alone but disagree on a
   common value are rejected exactly when the merged system has no
   rational solution.

2. Declared precision. A fact with value v and decimals=d contributes the
   closed interval [v-10^(-d)/2, v+10^(-d)/2]; decimals=INF contributes
   the singleton {v}. Duplicate facts of one metric in one aspect
   intersect their intervals; an empty intersection is inconsistent even
   when no equation is active. All arithmetic uses fractions.Fraction;
   there is no floating-point tolerance anywhere.

3. Joint activation. A (role, parent) group contributes the equation
   parent = sum(weight*child) to an aspect exactly when the parent and
   every child metric appear in that aspect; otherwise the whole group is
   silent for that aspect. The check is one simultaneous rational linear
   program per aspect (exact Bland-rule phase one), never per-equation
   satisfiability.

4. Verify-to-commit. Warehouse.ingest runs this verification inside the
   same BEGIN IMMEDIATE transaction, after format, qualification, batch
   and fact identity checks and the candidate fact inserts, but before
   the batch receipt insert and COMMIT. A CalculationError therefore
   rolls back every write of the attempt (facts, dataset binding,
   receipt), leaving the warehouse unchanged; a later batch simply
   re-verifies the full stored set plus its own candidates. Only the
   current dataset is read.
"""
from fractions import Fraction
import json
import re
from .errors import InputError

_DECIMAL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def parse_decimal(text):
    """Exact Fraction of a finite decimal in the instance value grammar."""
    if not _DECIMAL.fullmatch(text or ''):
        raise InputError('expected finite decimal')
    negative = text.startswith('-')
    whole, _dot, frac = text.lstrip('+-').partition('.')
    numerator = int(whole) if whole else 0
    denominator = 1
    if frac:
        numerator = numerator * 10 ** len(frac) + int(frac)
        denominator = 10 ** len(frac)
    value = Fraction(numerator, denominator)
    return -value if negative else value


def interval(value, decimals):
    """Closed declared-precision interval [lo, hi] of one fact."""
    point = parse_decimal(value)
    if decimals == 'INF':
        return (point, point)
    places = int(decimals)
    half = Fraction(1, 2 * 10 ** places) if places >= 0 else Fraction(10 ** -places, 2)
    return (point - half, point + half)


def inconsistent_groups(taxonomy, rows):
    """All inconsistent economic aspects among stored payload rows.

    Returns a list of {'aspect': ..., 'fact_ids': ...} sorted by the
    aspect sort-key JSON text; empty when every aspect is consistent.
    """
    if not taxonomy.calculations:
        return []
    metrics = taxonomy.calculation_metrics
    aspects = {}
    for row in rows:
        if row['metric'] not in metrics:
            continue
        aspect = {'entity': {'scheme': row['entity']['scheme'],
                             'identifier': row['entity']['identifier']},
                  'period': row['period'],
                  'segment': dict(row['dimensions']['segment']),
                  'scenario': dict(row['dimensions']['scenario']),
                  'unit': row['unit']}
        bucket = aspects.setdefault(_json(aspect), [aspect, {}, {}])
        spans, fact_ids = bucket[1], bucket[2]
        lo, hi = interval(row['value'], row['decimals'])
        span = spans.setdefault(row['metric'], [lo, hi])
        span[0] = max(span[0], lo)
        span[1] = min(span[1], hi)
        fact_ids.setdefault(row['metric'], []).append(row['id'])
    groups = []
    for key in sorted(aspects):
        aspect, spans, fact_ids = aspects[key]
        if not _aspect_feasible(taxonomy.calculation_groups, spans):
            groups.append({'aspect': aspect,
                           'fact_ids': sorted(fid for ids in fact_ids.values() for fid in ids)})
    return groups


def _aspect_feasible(groups, spans):
    """Whether one aspect's intervals and active equations share a solution."""
    metrics = sorted(spans)
    position = {metric: index for index, metric in enumerate(metrics)}
    n = len(metrics)
    lo = [spans[metric][0] for metric in metrics]
    hi = [spans[metric][1] for metric in metrics]
    equations = []
    for (_role, parent), children in groups:
        if parent not in position:
            continue
        if any(child not in position for child, _weight in children):
            continue
        row = [Fraction(0)] * n
        row[position[parent]] = Fraction(1)
        for child, weight in children:
            row[position[child]] -= weight
        equations.append(row)
    return _box_feasible(equations, lo, hi)


def _box_feasible(equations, lo, hi):
    """Whether equations[i] @ x == 0 with lo <= x <= hi has a rational solution."""
    n = len(lo)
    if any(lower > upper for lower, upper in zip(lo, hi)):
        return False
    equations = [row for row in equations if any(row)]
    if n == 0 or not equations:
        return True
    # Shift y = x - lo so 0 <= y <= hi - lo, then solve M w = g, w >= 0
    # with w = (y, z), z the upper-bound slacks.
    matrix, rhs = [], []
    for row in equations:
        matrix.append(list(row) + [Fraction(0)] * n)
        rhs.append(-sum(coef * lower for coef, lower in zip(row, lo)))
    for var in range(n):
        bound = [Fraction(0)] * (2 * n)
        bound[var] = bound[n + var] = Fraction(1)
        matrix.append(bound)
        rhs.append(hi[var] - lo[var])
    return _phase_one(matrix, rhs)


def _phase_one(matrix, rhs):
    """Exact Bland-rule phase one: does matrix @ w == rhs, w >= 0 have a solution?"""
    rows, columns = len(matrix), len(matrix[0])
    tableau, b = [], []
    for row, value in zip(matrix, rhs):
        row = list(row)
        if value < 0:
            row = [-coef for coef in row]
            value = -value
        tableau.append(row)
        b.append(value)
    basic = [columns + i for i in range(rows)]      # artificial variables
    nonbasic = list(range(columns))
    # Maximize -sum(artificials); artificial i = b[i] - sum(tableau[i]) @ w.
    cost = [sum(tableau[i][p] for i in range(rows)) for p in range(columns)]
    value = [-sum(b)]
    while True:
        enter = -1
        for p, var in enumerate(nonbasic):
            if cost[p] > 0 and (enter < 0 or var < nonbasic[enter]):
                enter = p
        if enter < 0:
            return value[0] == 0
        leave, ratio = -1, None
        for i in range(rows):
            coef = tableau[i][enter]
            if coef > 0:
                candidate = b[i] / coef
                if leave < 0 or candidate < ratio or (candidate == ratio and basic[i] < basic[leave]):
                    leave, ratio = i, candidate
        if leave < 0:
            raise AssertionError('phase-one objective is bounded above by zero')
        _pivot(tableau, b, cost, value, basic, nonbasic, leave, enter)


def _pivot(tableau, b, cost, value, basic, nonbasic, leave, enter):
    """Swap basic[leave] and nonbasic[enter] in the dictionary, exactly."""
    pivot = tableau[leave][enter]
    width = len(nonbasic)
    row = [coef / pivot for coef in tableau[leave]]
    row[enter] = Fraction(1) / pivot                # coefficient of the leaving variable
    b[leave] /= pivot
    for i in range(len(tableau)):
        if i == leave:
            continue
        factor = tableau[i][enter]
        if factor:
            target = tableau[i]
            for p in range(width):
                if p != enter:
                    target[p] -= factor * row[p]
            target[enter] = -factor * row[enter]
            b[i] -= factor * b[leave]
    factor = cost[enter]
    if factor:
        for p in range(width):
            if p != enter:
                cost[p] -= factor * row[p]
        cost[enter] = -factor * row[enter]
        value[0] += factor * b[leave]
    tableau[leave] = row
    basic[leave], nonbasic[enter] = nonbasic[enter], basic[leave]
