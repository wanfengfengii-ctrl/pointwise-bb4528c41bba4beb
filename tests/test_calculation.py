"""Business verification of the calculation extension (CALCULATIONS.md)."""
import json
import random
import subprocess
import sys
import tempfile
import time
import unittest
from fractions import Fraction
from itertools import count
from pathlib import Path

import calculation_samples
from scenarios.calculation_reference import reference_feasible
from xbrl_local import (Taxonomy, Instance, Warehouse, Receipt, InputError,
                        ConflictError, QualificationError, CalculationError)
from xbrl_local.calculation import _box_feasible, interval, parse_decimal

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples'
F = Fraction


def calc_taxonomy(edges, metrics=()):
    """Relation package XML; edges are (role, parent, child, weight text)."""
    names = set(metrics)
    for _role, parent, child, _weight in edges:
        names.update((parent, child))
    concepts = ''.join('<concept name="m:%s" kind="metric"/>' % name for name in sorted(names))
    arcs = ''.join('<arc kind="summation-item" role="%s" from="m:%s" to="m:%s" weight="%s"/>'
                   % edge for edge in edges)
    return ('<taxonomy xmlns="urn:local-xbrl:1" xmlns:m="urn:calculation">'
            + concepts + arcs + '</taxonomy>')


def custom_instance(facts, contexts=None):
    """facts: (id, metric, value, decimals or None, context id).

    contexts maps a context id to overrides: day, measure, scheme,
    identifier, segment, scenario (raw explicit dimension maps).
    """
    contexts = contexts or {}
    order = []
    for _fid, _metric, _value, _decimals, cid in facts:
        if cid not in order:
            order.append(cid)
    xml = ['<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
           'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
           'xmlns:m="urn:calculation" xmlns:u="urn:calculation:unit">']
    for cid in order:
        options = contexts.get(cid, {})
        segment = options.get('segment')
        scenario = options.get('scenario')
        seg = scn = ''
        if segment:
            seg = '<xbrli:segment>' + ''.join(
                '<xbrldi:explicitMember dimension="%s">%s</xbrldi:explicitMember>' % pair
                for pair in segment.items()) + '</xbrli:segment>'
        if scenario:
            scn = '<xbrli:scenario>' + ''.join(
                '<xbrldi:explicitMember dimension="%s">%s</xbrldi:explicitMember>' % pair
                for pair in scenario.items()) + '</xbrli:scenario>'
        xml.append('<xbrli:context id="%s"><xbrli:entity><xbrli:identifier scheme="%s">%s'
                   '</xbrli:identifier>%s</xbrli:entity><xbrli:period><xbrli:instant>%s'
                   '</xbrli:instant></xbrli:period>%s</xbrli:context>' % (
                       cid, options.get('scheme', 'urn:calculation:entity'),
                       options.get('identifier', 'E'), seg, options.get('day', '2026-10-31'), scn))
        xml.append('<xbrli:unit id="u-%s"><xbrli:measure>%s</xbrli:measure></xbrli:unit>' % (
            cid, options.get('measure', 'u:count')))
    for fid, metric, value, decimals, cid in facts:
        attribute = ' decimals="%s"' % decimals if decimals is not None else ''
        xml.append('<m:%s id="%s" contextRef="%s" unitRef="u-%s"%s>%s</m:%s>' % (
            metric, fid, cid, cid, attribute, value, metric))
    xml.append('</xbrli:xbrl>')
    return ''.join(xml)


DIM_TAXONOMY = (
    '<taxonomy xmlns="urn:local-xbrl:1" xmlns:m="urn:calculation">'
    '<concept name="m:P" kind="metric"/><concept name="m:X" kind="metric"/>'
    '<concept name="m:Cube" kind="cube"/><concept name="m:Dim" kind="dimension"/>'
    '<concept name="m:Mem" kind="member"/><concept name="m:Other" kind="member"/>'
    '<arc kind="all" role="r" from="m:P" to="m:Cube" targetRole="t"/>'
    '<arc kind="all" role="r" from="m:X" to="m:Cube" targetRole="t"/>'
    '<arc kind="hypercube-dimension" role="t" from="m:Cube" to="m:Dim" targetRole="d"/>'
    '<arc kind="dimension-domain" role="d" from="m:Dim" to="m:Mem"/>'
    '<arc kind="dimension-domain" role="d" from="m:Dim" to="m:Other"/>'
    '<arc kind="summation-item" role="c" from="m:P" to="m:X" weight="1"/></taxonomy>')


class CalculationCase(unittest.TestCase):
    def setUp(self):
        self.store = Warehouse()
        self.addCleanup(self.store.close)
        self.batches = count(1)

    def ingest(self, taxonomy, instance, dataset='lab'):
        return self.store.ingest(dataset, 'b%d' % next(self.batches), taxonomy, instance)

    def parsed(self, edges, metrics=()):
        return Taxonomy.from_xml(calc_taxonomy(edges, metrics))

    def sample(self, rows, **kwargs):
        return Instance.from_xml(calculation_samples.instance_xml(rows, **kwargs))

    def custom(self, facts, contexts=None):
        return Instance.from_xml(custom_instance(facts, contexts))


class FixtureTests(unittest.TestCase):
    def test_provided_sample_fixtures_still_parse(self):
        result = calculation_samples.check()
        self.assertEqual(result['fixtures'], 3)


class DocumentedFlowTests(CalculationCase):
    def setUp(self):
        super().setUp()
        self.taxonomy = Taxonomy.from_file(EXAMPLES / 'calculation-taxonomy.xml')
        self.first = Instance.from_file(EXAMPLES / 'calculation-first.xml')
        self.second = Instance.from_file(EXAMPLES / 'calculation-second.xml')
        self.other = Instance.from_file(EXAMPLES / 'calculation-other-period.xml')

    def test_cross_batch_joint_rejection_matches_document(self):
        receipt = self.store.ingest('lab', 'first', self.taxonomy, self.first)
        self.assertEqual(receipt, Receipt('lab', 'first', 2))
        with self.assertRaises(CalculationError) as caught:
            self.store.ingest('lab', 'second', self.taxonomy, self.second)
        error = caught.exception
        self.assertIsInstance(error, InputError)
        self.assertTrue(str(error).startswith('CALCULATION_INCONSISTENT'))
        expected = [{'aspect': {'entity': {'scheme': 'urn:calculation:entity', 'identifier': 'E'},
                                'period': 'instant:2026-10-31', 'segment': {}, 'scenario': {},
                                'unit': '{urn:calculation:unit}count'},
                     'fact_ids': ['p', 'q', 'x']}]
        self.assertEqual(error.groups, expected)
        self.assertEqual(json.dumps(error.groups, ensure_ascii=False, separators=(',', ':')),
                         '[{"aspect":{"entity":{"scheme":"urn:calculation:entity","identifier":"E"},'
                         '"period":"instant:2026-10-31","segment":{},"scenario":{},'
                         '"unit":"{urn:calculation:unit}count"},"fact_ids":["p","q","x"]}]')
        for group in error.groups:
            self.assertEqual(set(group), {'aspect', 'fact_ids'})
            self.assertEqual(set(group['aspect']), {'entity', 'period', 'segment', 'scenario', 'unit'})
            self.assertEqual(set(group['aspect']['entity']), {'scheme', 'identifier'})
        # The failed batch changed nothing: facts, receipts, replay.
        self.assertEqual([row['id'] for row in self.store.read('lab')], ['p', 'x'])
        self.assertEqual(self.store.receipts('lab'), [Receipt('lab', 'first', 2)])
        self.assertEqual(self.store.ingest('lab', 'first', self.taxonomy, self.first), receipt)
        # The same batch id may be retried with the other-period instance.
        retry = self.store.ingest('lab', 'second', self.taxonomy, self.other)
        self.assertEqual(retry, Receipt('lab', 'second', 1))
        self.assertEqual([row['id'] for row in self.store.read('lab')], ['p', 'q', 'x'])
        self.assertEqual([r.batch_id for r in self.store.receipts('lab')], ['first', 'second'])

    def test_first_and_second_facts_in_one_batch_fail(self):
        combined = self.sample([('x', 'X', '0.5', '0'), ('p', 'P', '0', 'INF'), ('q', 'Q', '1', 'INF')])
        with self.assertRaises(CalculationError):
            self.store.ingest('lab', 'joined', self.taxonomy, combined)
        self.assertEqual(self.store.read('lab'), [])
        self.assertEqual(self.store.receipts('lab'), [])
        # A failed first batch leaves no dataset binding: another package may retry.
        relaxed = self.parsed([('p', 'P', 'X', '1')], metrics=('Q',))
        receipt = self.store.ingest('lab', 'joined', relaxed, combined)
        self.assertEqual(receipt.inserted, 3)

    def test_failed_batch_leaves_no_trace_after_reopen(self):
        with tempfile.TemporaryDirectory(prefix='local-xbrl-calc-') as directory:
            path = Path(directory) / 'calc.sqlite'
            with Warehouse(path) as warehouse:
                warehouse.ingest('lab', 'first', self.taxonomy, self.first)
                with self.assertRaises(CalculationError):
                    warehouse.ingest('lab', 'second', self.taxonomy, self.second)
            with Warehouse(path) as warehouse:
                self.assertEqual([row['id'] for row in warehouse.read('lab')], ['p', 'x'])
                self.assertEqual([r.batch_id for r in warehouse.receipts('lab')], ['first'])
                # Reopening continues joint verification against stored facts.
                warehouse.ingest('lab', 'second', self.taxonomy, self.other)
                blocking = self.sample([('x2', 'X', '0', 'INF')], day='2026-11-01',
                                       context_id='c2', unit_id='u2')
                with self.assertRaises(CalculationError) as caught:
                    warehouse.ingest('lab', 'third', self.taxonomy, blocking)
                self.assertEqual(caught.exception.groups[0]['fact_ids'], ['q', 'x2'])
                self.assertEqual([row['id'] for row in warehouse.read('lab')], ['p', 'q', 'x'])
                completing = self.sample([('x2', 'X', '1', 'INF')], day='2026-11-01',
                                         context_id='c2', unit_id='u2')
                self.assertEqual(warehouse.ingest('lab', 'third', self.taxonomy, completing).inserted, 1)
            with Warehouse(path) as warehouse:
                self.assertEqual([r.batch_id for r in warehouse.receipts('lab')],
                                 ['first', 'second', 'third'])


class IntervalTests(unittest.TestCase):
    def test_interval_endpoints_and_decimals(self):
        self.assertEqual(interval('0.5', '0'), (F(0), F(1)))
        self.assertEqual(interval('1', 'INF'), (F(1), F(1)))
        self.assertEqual(interval('-1.50', '-1'), (F(-13, 2), F(7, 2)))
        self.assertEqual(interval('10', '-2'), (F(-40), F(60)))
        self.assertEqual(interval('.25', '2'), (F(1, 4) - F(1, 200), F(1, 4) + F(1, 200)))
        self.assertEqual(interval('+3.', '+1'), (F(3) - F(1, 20), F(3) + F(1, 20)))

    def test_parse_decimal_grammar(self):
        self.assertEqual(parse_decimal('+1.50'), F(3, 2))
        self.assertEqual(parse_decimal('-.5'), F(-1, 2))
        self.assertEqual(parse_decimal('0'), F(0))
        for bad in ('', '1e3', 'NaN', 'INF', 'inf', '1.2.3', '1/2', '.', '+', '0x1'):
            with self.subTest(text=bad), self.assertRaises(InputError):
                parse_decimal(bad)


class TaxonomyFormatTests(unittest.TestCase):
    def tax(self, arcs, metrics=('X', 'P')):
        concepts = ''.join('<concept name="m:%s" kind="metric"/>' % m for m in metrics)
        return ('<taxonomy xmlns="urn:local-xbrl:1" xmlns:m="urn:calculation">'
                + concepts + arcs + '</taxonomy>')

    def arc(self, weight='1', **extra):
        attributes = ''.join(' %s="%s"' % pair for pair in extra.items())
        return ('<arc kind="summation-item" role="r" from="m:P" to="m:X" weight="%s"%s/>'
                % (weight, attributes))

    def test_weight_grammar_and_nonzero(self):
        for good in ('1', '+1', '-1', '1.5', '.5', '-.5', '0.25', '10.', '000.500'):
            with self.subTest(weight=good):
                Taxonomy.from_xml(self.tax(self.arc(good)))
        for bad in ('0', '0.0', '-0', '+0.00', '1e2', 'NaN', 'INF', 'inf', '1/2', ''):
            with self.subTest(weight=bad), self.assertRaises(InputError):
                Taxonomy.from_xml(self.tax(self.arc(bad)))

    def test_attributes_are_exactly_the_five(self):
        Taxonomy.from_xml(self.tax(self.arc()))
        for extra in ({'targetRole': 't'}, {'contextElement': 'scenario'},
                      {'usable': 'true'}, {'closed': 'true'}, {'order': '1'}):
            with self.subTest(extra=extra), self.assertRaises(InputError):
                Taxonomy.from_xml(self.tax(self.arc(**extra)))
        with self.assertRaises(InputError):
            Taxonomy.from_xml(self.tax('<arc kind="summation-item" role="r" from="m:P" to="m:X"/>'))

    def test_duplicate_edge_rejected_even_with_different_weight(self):
        pair = self.arc('1') + self.arc('2')
        with self.assertRaises(InputError):
            Taxonomy.from_xml(self.tax(pair))
        shifted = self.arc('1') + self.arc('2').replace('role="r"', 'role="s"')
        Taxonomy.from_xml(self.tax(shifted))

    def test_endpoints_must_be_declared_metrics(self):
        with self.assertRaises(InputError):
            Taxonomy.from_xml(self.tax(self.arc(), metrics=('P',)))  # X undeclared
        cube = ('<taxonomy xmlns="urn:local-xbrl:1" xmlns:m="urn:calculation">'
                '<concept name="m:P" kind="metric"/><concept name="m:C" kind="cube"/>'
                '<arc kind="summation-item" role="r" from="m:P" to="m:C" weight="1"/></taxonomy>')
        with self.assertRaises(InputError):
            Taxonomy.from_xml(cube)

    def test_metric_and_group_limits(self):
        metrics = tuple('M%d' % i for i in range(9))
        chain = ''.join('<arc kind="summation-item" role="r%d" from="m:M%d" to="m:M%d" weight="1"/>'
                        % (i, i, i + 1) for i in range(8))
        with self.assertRaises(InputError):  # 9 metrics
            Taxonomy.from_xml(self.tax(chain, metrics))
        fan = ''.join('<arc kind="summation-item" role="r%d" from="m:M0" to="m:M1" weight="1"/>' % i
                      for i in range(9))
        with self.assertRaises(InputError):  # 9 groups
            Taxonomy.from_xml(self.tax(fan, metrics[:8]))
        cycle = ''.join('<arc kind="summation-item" role="r%d" from="m:M%d" to="m:M%d" weight="1"/>'
                        % (i, i, (i + 1) % 8) for i in range(8))
        taxonomy = Taxonomy.from_xml(self.tax(cycle, metrics[:8]))  # exactly 8 and 8
        self.assertEqual(len(taxonomy.calculations), 8)
        self.assertEqual(len(taxonomy.calculation_metrics), 8)
        self.assertEqual(len(taxonomy.calculation_groups), 8)

    def test_calculation_edges_do_not_change_dimension_qualification(self):
        taxonomy = Taxonomy.from_xml(calc_taxonomy([('r', 'P', 'X', '1')]))
        self.assertTrue(taxonomy.qualifies('{urn:calculation}P', {}, {}))
        self.assertFalse(taxonomy.qualifies('{urn:calculation}P', {'{urn:calculation}Dim': '{urn:calculation}Mem'}, {}))
        plain = Taxonomy.from_file(EXAMPLES / 'taxonomy.xml')
        self.assertEqual(plain.calculations, ())
        self.assertEqual(plain.calculation_metrics, frozenset())


class BehaviorTests(CalculationCase):
    def test_negative_weights(self):
        taxonomy = self.parsed([('r', 'P', 'X', '-1')])  # P = -X
        self.assertEqual(self.ingest(taxonomy, self.sample([('p', 'P', '-2', 'INF'), ('x', 'X', '2', 'INF')])).inserted, 2)
        with self.assertRaises(CalculationError):
            self.ingest(taxonomy, self.sample([('p2', 'P', '2', 'INF')], context_id='c2', unit_id='u2'))

    def test_self_loop(self):
        doubling = self.parsed([('r', 'A', 'A', '2')])  # A = 2A forces A = 0
        self.assertEqual(self.ingest(doubling, self.sample([('a', 'A', '0', 'INF')])).inserted, 1)
        with self.assertRaises(CalculationError):
            self.ingest(doubling, self.sample([('a2', 'A', '3', 'INF')], context_id='c2', unit_id='u2'))
        identity = self.parsed([('r', 'A', 'A', '1')])  # A = A is always satisfied
        self.assertEqual(self.ingest(identity, self.sample([('b', 'A', '7', 'INF')]), dataset='other').inserted, 1)

    def test_cycle(self):
        taxonomy = self.parsed([('r1', 'A', 'B', '1'), ('r2', 'B', 'A', '1')])  # A = B
        self.assertEqual(self.ingest(taxonomy, self.sample([('a', 'A', '1', 'INF'), ('b', 'B', '1', 'INF')])).inserted, 2)
        with self.assertRaises(CalculationError):
            self.ingest(taxonomy, self.sample([('a2', 'A', '1', 'INF'), ('b2', 'B', '2', 'INF')],
                                              context_id='c2', unit_id='u2'))

    def test_rank_deficient_system(self):
        taxonomy = self.parsed([('r1', 'P', 'X', '1'), ('r2', 'Q', 'X', '1'), ('r3', 'P', 'Q', '1')])
        consistent = self.sample([('p', 'P', '1', 'INF'), ('q', 'Q', '1', 'INF'), ('x', 'X', '1', 'INF')])
        self.assertEqual(self.ingest(taxonomy, consistent).inserted, 3)
        inconsistent = self.sample([('p', 'P', '1', 'INF'), ('q', 'Q', '2', 'INF'), ('x', 'X', '1', 'INF')])
        with self.assertRaises(CalculationError):
            self.ingest(taxonomy, inconsistent, dataset='other')

    def test_missing_child_completion_activates_group(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1'), ('r', 'P', 'Y', '1')])  # P = X + Y
        self.assertEqual(self.ingest(taxonomy, self.sample([('p', 'P', '3', 'INF'), ('x', 'X', '1', 'INF')])).inserted, 2)
        with self.assertRaises(CalculationError) as caught:
            self.ingest(taxonomy, self.sample([('y', 'Y', '1', 'INF')], context_id='c2', unit_id='u2'))
        self.assertEqual(caught.exception.groups[0]['fact_ids'], ['p', 'x', 'y'])
        self.assertEqual(self.ingest(taxonomy, self.sample([('y', 'Y', '2', 'INF')],
                                                           context_id='c2', unit_id='u2')).inserted, 1)

    def test_aspect_isolation(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        # Each pair would empty-intersect if merged; separate aspects stay consistent.
        cases = [
            {'c1': {}, 'c2': {'day': '2026-11-01'}},                                  # period
            {'c1': {}, 'c2': {'measure': 'u:other'}},                                 # unit
            {'c1': {}, 'c2': {'identifier': 'F'}},                                    # entity
            {'c1': {}, 'c2': {'scheme': 'urn:calculation:other'}},                    # scheme
        ]
        for index, contexts in enumerate(cases):
            with self.subTest(isolation=index):
                facts = [('p1', 'P', '0', 'INF', 'c1'), ('x1', 'X', '0', 'INF', 'c1'),
                         ('p2', 'P', '1', 'INF', 'c2'), ('x2', 'X', '1', 'INF', 'c2')]
                self.assertEqual(self.ingest(taxonomy, self.custom(facts, contexts),
                                             dataset='iso%d' % index).inserted, 4)
        dimensioned = Taxonomy.from_xml(DIM_TAXONOMY)
        facts = [('p1', 'P', '0', 'INF', 'c1'), ('x1', 'X', '0', 'INF', 'c1'),
                 ('p2', 'P', '1', 'INF', 'c2'), ('x2', 'X', '1', 'INF', 'c2')]
        contexts = {'c1': {'segment': {'m:Dim': 'm:Mem'}}, 'c2': {'segment': {'m:Dim': 'm:Other'}}}
        self.assertEqual(self.ingest(dimensioned, self.custom(facts, contexts), dataset='dim').inserted, 4)

    def test_endpoint_intersection_is_feasible(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        touching = self.custom([('x1', 'X', '0', '0', 'c'), ('x2', 'X', '1', '0', 'c'),
                                ('p', 'P', '0.5', 'INF', 'c')])
        self.assertEqual(self.ingest(taxonomy, touching).inserted, 3)

    def test_duplicate_facts_with_empty_intersection_are_rejected(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        apart = self.custom([('x1', 'X', '0', '0', 'c'), ('x2', 'X', '1.01', '2', 'c'),
                             ('p', 'P', '0.5', 'INF', 'c')])
        with self.assertRaises(CalculationError) as caught:
            self.ingest(taxonomy, apart)
        self.assertEqual(caught.exception.groups[0]['fact_ids'], ['p', 'x1', 'x2'])
        points = self.custom([('x1', 'X', '0', 'INF', 'c'), ('x2', 'X', '1', 'INF', 'c')])
        with self.assertRaises(CalculationError):
            self.ingest(taxonomy, points, dataset='other')

    def test_negative_decimals(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        within = self.custom([('x', 'X', '10', '-1', 'c'), ('p', 'P', '12', 'INF', 'c')])
        self.assertEqual(self.ingest(taxonomy, within).inserted, 2)
        outside = self.custom([('x', 'X', '10', '-1', 'c'), ('p', 'P', '16', 'INF', 'c')])
        with self.assertRaises(CalculationError):
            self.ingest(taxonomy, outside, dataset='other')

    def test_omitted_decimals_means_inf(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        exact = self.custom([('x', 'X', '3', None, 'c'), ('p', 'P', '3', 'INF', 'c')])
        self.assertEqual(self.ingest(taxonomy, exact).inserted, 2)
        off = self.custom([('x', 'X', '3', None, 'c'), ('p', 'P', '3.0000001', 'INF', 'c')])
        with self.assertRaises(CalculationError):
            self.ingest(taxonomy, off, dataset='other')

    def test_non_calculation_metrics_keep_original_acceptance(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')], metrics=('Y',))
        duplicates = self.custom([('y1', 'Y', '0', 'INF', 'c'), ('y2', 'Y', '99', 'INF', 'c')])
        self.assertEqual(self.ingest(taxonomy, duplicates).inserted, 2)

    def test_multiple_inconsistent_aspects_are_all_listed_and_sorted(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        facts = [('p1', 'P', '0', 'INF', 'c1'), ('x1', 'X', '1', 'INF', 'c1'),
                 ('p2', 'P', '2', 'INF', 'c2'), ('x2', 'X', '3', 'INF', 'c2'),
                 ('p3', 'P', '4', 'INF', 'c3'), ('x3', 'X', '4', 'INF', 'c3')]
        contexts = {'c2': {'day': '2026-11-01'}, 'c3': {'day': '2026-11-02'}}
        with self.assertRaises(CalculationError) as caught:
            self.ingest(taxonomy, self.custom(facts, contexts))
        groups = caught.exception.groups
        self.assertEqual([g['fact_ids'] for g in groups], [['p1', 'x1'], ['p2', 'x2']])
        self.assertEqual([g['aspect']['period'] for g in groups],
                         ['instant:2026-10-31', 'instant:2026-11-01'])

    def test_identity_and_qualification_errors_precede_calculation(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        self.ingest(taxonomy, self.custom([('x', 'X', '0', 'INF', 'c'), ('p', 'P', '0', 'INF', 'c')]))
        conflict = self.custom([('x', 'X', '9', 'INF', 'c'), ('p2', 'P', '0', 'INF', 'c')])
        with self.assertRaises(ConflictError):
            self.ingest(taxonomy, conflict)
        unqualified = self.custom([('p3', 'P', '0', 'INF', 'c3'), ('x3', 'X', '9', 'INF', 'c3')],
                                  {'c3': {'segment': {'m:Dim': 'm:Mem'}}})
        with self.assertRaises(QualificationError):
            self.ingest(taxonomy, unqualified)

    def test_replay_and_conflicts_with_calculation_taxonomy(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        instance = self.custom([('x', 'X', '0', 'INF', 'c'), ('p', 'P', '0', 'INF', 'c')])
        receipt = self.store.ingest('lab', 'fixed', taxonomy, instance)
        before = self.store.read('lab')
        self.assertEqual(self.store.ingest('lab', 'fixed', taxonomy, instance), receipt)
        self.assertEqual(self.store.read('lab'), before)
        changed = self.custom([('x', 'X', '0', 'INF', 'c'), ('p', 'P', '1', 'INF', 'c')])
        with self.assertRaises(ConflictError):
            self.store.ingest('lab', 'fixed', taxonomy, changed)
        self.assertEqual(self.store.ingest('lab', 'another', taxonomy, instance).inserted, 0)

    def test_datasets_are_verified_independently(self):
        taxonomy = self.parsed([('r', 'P', 'X', '1')])
        self.ingest(taxonomy, self.custom([('x', 'X', '0', 'INF', 'c'), ('p', 'P', '0', 'INF', 'c')]), dataset='a')
        self.assertEqual(self.ingest(taxonomy, self.custom(
            [('x', 'X', '1', 'INF', 'c'), ('p', 'P', '1', 'INF', 'c')]), dataset='b').inserted, 2)

    def test_eight_metric_boundary_timing(self):
        names = ('X', 'P', 'Q', 'Y', 'A', 'B', 'C', 'D')
        edges = [(names[i], names[i], names[(i + 1) % 8], '1') for i in range(8)]
        taxonomy = self.parsed(edges)
        equal = self.sample([('f%d' % i, name, '5', 'INF') for i, name in enumerate(names)])
        start = time.perf_counter()
        self.assertEqual(self.ingest(taxonomy, equal).inserted, 8)
        feasible_elapsed = time.perf_counter() - start
        broken = self.sample([('f%d' % i, name, '6' if name == 'D' else '5', 'INF')
                              for i, name in enumerate(names)])
        start = time.perf_counter()
        with self.assertRaises(CalculationError):
            self.ingest(taxonomy, broken, dataset='other')
        infeasible_elapsed = time.perf_counter() - start
        print('eight-metric joint verification: feasible %.6fs, infeasible %.6fs'
              % (feasible_elapsed, infeasible_elapsed))


class JointFeasibilityReferenceTests(unittest.TestCase):
    def test_degenerate_low_dimensional_cases(self):
        cases = [
            ([[F(1), F(-1)]], [F(0), F(0)], [F(2), F(2)], True),          # line through box
            ([[F(1), F(-1)]], [F(2), F(2)], [F(2), F(2)], True),          # only point (2,2)
            ([[F(1), F(-1)]], [F(0), F(3)], [F(1), F(4)], False),         # parallel, disjoint
            ([[F(1), F(1)]], [F(1), F(1)], [F(1), F(1)], False),          # x+y=0 away from box
            ([[F(1), F(1)]], [F(-1), F(-1)], [F(1), F(1)], True),         # x+y=0 segment
            ([[F(2), F(2)], [F(1), F(1)]], [F(0), F(0)], [F(3), F(3)], True),   # rank deficient
            ([[F(1), F(0)], [F(0), F(1)]], [F(1), F(1)], [F(2), F(2)], False),  # origin forced
            ([[F(1), F(1), F(1)]], [F(0)] * 3, [F(0)] * 3, True),         # plane through origin
            ([[F(1), F(1), F(1)]], [F(1)] * 3, [F(2)] * 3, False),        # plane misses box
            ([[F(1)]], [F(0)], [F(0)], True),                             # forced zero, point box
            ([[F(1)]], [F(1)], [F(1)], False),                            # forced zero, box away
        ]
        for equations, lo, hi, expected in cases:
            with self.subTest(equations=equations, lo=lo, hi=hi):
                self.assertEqual(_box_feasible([list(row) for row in equations], lo, hi), expected)
                self.assertEqual(reference_feasible(equations, lo, hi), expected)

    def test_random_small_systems_match_independent_reference(self):
        rng = random.Random(20261116)
        for trial in range(500):
            n = rng.randint(1, 4)
            equations = [[F(rng.randint(-2, 2), rng.choice((1, 1, 2))) for _ in range(n)]
                         for _ in range(rng.randint(0, 3))]
            lo, hi = [], []
            for _ in range(n):
                lower = F(rng.randint(-3, 3), rng.choice((1, 2)))
                lo.append(lower)
                hi.append(lower + F(rng.randint(0, 4), rng.choice((1, 2))))
            with self.subTest(trial=trial):
                self.assertEqual(_box_feasible([list(row) for row in equations], lo, hi),
                                 reference_feasible(equations, lo, hi))


class CalculationCliTests(unittest.TestCase):
    def test_cli_import_joint_rejection_and_read(self):
        with tempfile.TemporaryDirectory(prefix='local-xbrl-calc-cli-') as directory:
            path = Path(directory) / 'cli.sqlite'

            def call(*args):
                result = subprocess.run([sys.executable, '-B', '-m', 'xbrl_local', '--db', str(path), *args],
                                        cwd=ROOT, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.stderr, '')
                return result.returncode, json.loads(result.stdout)

            base = ('import', '--dataset', 'lab', '--batch', 'first', '--taxonomy',
                    str(EXAMPLES / 'calculation-taxonomy.xml'), '--instance',
                    str(EXAMPLES / 'calculation-first.xml'))
            status, receipt = call(*base)
            self.assertEqual((status, receipt), (0, {'dataset': 'lab', 'batch_id': 'first', 'inserted': 2}))
            second = list(base)
            second[4] = 'second'
            second[-1] = str(EXAMPLES / 'calculation-second.xml')
            status, error = call(*second)
            self.assertEqual(status, 2)
            self.assertTrue(error['error'].startswith('CALCULATION_INCONSISTENT'))
            self.assertNotIn('issues', error)
            status, rows = call('read', '--dataset', 'lab')
            self.assertEqual(status, 0)
            self.assertEqual([row['id'] for row in rows], ['p', 'x'])
            other = list(second)
            other[-1] = str(EXAMPLES / 'calculation-other-period.xml')
            status, receipt = call(*other)
            self.assertEqual((status, receipt), (0, {'dataset': 'lab', 'batch_id': 'second', 'inserted': 1}))


if __name__ == '__main__':
    unittest.main()
