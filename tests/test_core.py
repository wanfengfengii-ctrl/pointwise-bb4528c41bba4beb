import unittest
import samples
from scenarios.qualification import run
from xbrl_local import (Taxonomy, Instance, Warehouse, InputError,
                        ConflictError, QualificationError)


class CoreTests(unittest.TestCase):
    def __init__(self, methodName='runTest', *, fixtures=None):
        super().__init__(methodName)
        self.fixtures = fixtures

    def setUp(self):
        self.taxonomy_text, self.accepted_text, self.rejected_text = (
            self.fixtures if self.fixtures is not None else
            (samples.taxonomy_xml(), samples.accepted_xml(), samples.rejected_xml()))
        self.taxonomy = Taxonomy.from_xml(self.taxonomy_text)
        self.good = Instance.from_xml(self.accepted_text)
        self.store = Warehouse()
        self.addCleanup(self.store.close)

    def batch(self, rows):
        return samples.batch(rows, self.accepted_text)

    def snapshot(self):
        return tuple(self.store._db.iterdump())

    def test_complete_business_matrix(self):
        result = run(self.taxonomy_text, self.accepted_text)
        self.assertEqual(result['checked'], 91)
        self.assertEqual(len(result['accepted']), 19)

    def test_accepted_payload_and_replay(self):
        receipt = self.store.ingest('lab', 'initial', self.taxonomy, self.good)
        self.assertEqual(receipt.inserted, 9)
        rows = self.store.read('lab')
        self.assertEqual([r['id'] for r in rows], list('abcdefghi'))
        self.assertEqual([r['metric'] for r in rows], ['{urn:lab}' + m for m in (
            'Revenue', 'Expense', 'Combined', 'Alternative', 'Revenue',
            'OpenMetric', 'ScenarioMetric', 'Bare', 'Revenue')])
        for row in rows:
            self.assertEqual(row['value'], '10')
            self.assertEqual(row['decimals'], '0')
            self.assertEqual(row['entity'], {'scheme': 'urn:lab:entity', 'identifier': 'LAB-1'})
            self.assertEqual(row['period'], 'instant:2026-10-31')
            self.assertEqual(row['unit'], '{http://www.xbrl.org/2003/iso4217}USD')
        self.assertEqual(rows[0]['dimensions'], {'segment': {'{urn:lab}Region': '{urn:lab}North'}, 'scenario': {}})
        self.assertEqual(rows[6]['dimensions'], {'segment': {}, 'scenario': {'{urn:lab}Region': '{urn:lab}North'}})
        before = self.snapshot()
        self.assertEqual(self.store.ingest('lab', 'initial', self.taxonomy, self.good), receipt)
        self.assertEqual(self.snapshot(), before)
        reverse = self.batch([(f.id, f.metric.split('}')[1], f.context_id, f.value)
                                 for f in reversed(self.good.facts)])
        self.assertEqual(self.store.ingest('lab', 'initial', self.taxonomy, Instance.from_xml(reverse)), receipt)
        self.assertEqual(self.store.ingest('lab', 'another', self.taxonomy, self.good).inserted, 0)
        self.assertEqual(self.store.read('lab'), rows)
        self.assertEqual(self.store.ingest('other', 'initial', self.taxonomy, self.good).inserted, 9)
        rows[0]['value'] = 'changed by caller'
        self.assertEqual(self.store.read('lab')[0]['value'], '10')

    def test_rejected_batch_is_atomic_and_reports_all_fact_ids(self):
        self.store.ingest('lab', 'initial', self.taxonomy, self.good)
        before = self.snapshot()
        with self.assertRaises(QualificationError) as caught:
            self.store.ingest('lab', 'invalid', self.taxonomy, Instance.from_xml(self.rejected_text))
        self.assertEqual([i.fact_id for i in caught.exception.issues],
                         ['bad-b', 'bad-ban', 'bad-hidden', 'bad-default', 'bad-extra', 'bad-missing'])
        self.assertTrue(all(i.context_id for i in caught.exception.issues))
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(QualificationError):
            self.store.ingest('new', 'invalid', self.taxonomy, Instance.from_xml(self.rejected_text))
        self.assertEqual(self.snapshot(), before)

    def test_late_fact_conflict_rolls_back_earlier_insert_and_receipt(self):
        self.store.ingest('lab', 'initial', self.taxonomy, self.good)
        before = self.snapshot()
        conflict = self.batch([('000-new', 'Revenue', 'north', '1'), ('i', 'Revenue', 'north', '99')])
        with self.assertRaises(ConflictError):
            self.store.ingest('lab', 'late-conflict', self.taxonomy, Instance.from_xml(conflict))
        self.assertEqual(self.snapshot(), before)
        corrected = self.batch([('000-new', 'Revenue', 'north', '1')])
        self.assertEqual(self.store.ingest('lab', 'late-conflict', self.taxonomy,
                                         Instance.from_xml(corrected)).inserted, 1)
        self.assertEqual(self.store.ingest('lab', 'initial', self.taxonomy, self.good).inserted, 9)

    def test_batch_identity_and_taxonomy_binding(self):
        self.store.ingest('lab', 'initial', self.taxonomy, self.good)
        before = self.snapshot()
        different = Instance.from_xml(self.batch([('fresh', 'Revenue', 'north', '10')]))
        with self.assertRaises(ConflictError):
            self.store.ingest('lab', 'initial', self.taxonomy, different)
        equivalent_bundle = Taxonomy.from_xml(self.taxonomy_text + '\n')
        with self.assertRaises(ConflictError):
            self.store.ingest('lab', 'other-bundle', equivalent_bundle, different)
        self.assertEqual(self.snapshot(), before)

    def test_namespace_scopes_on_qname_values(self):
        source = self.batch([('scope', 'Revenue', 'north', '10')])
        source = source.replace('dimension="m:Region">m:North',
                                'xmlns:m="urn:other" xmlns:d="urn:lab" dimension="d:Region">d:North', 1)
        parsed = Instance.from_xml(source)
        self.assertEqual(dict(parsed.contexts['north'].segment), {'{urn:lab}Region': '{urn:lab}North'})
        self.assertEqual(dict(parsed.contexts['south'].segment), {'{urn:lab}Region': '{urn:lab}South'})
        self.assertEqual(self.store.ingest('lab', 'scoped', self.taxonomy, parsed).inserted, 1)
        bad = source.replace('dimension="d:Region">d:North', 'dimension="d:Region">m:North', 1)
        with self.assertRaises(QualificationError):
            self.store.ingest('lab', 'bad-scope', self.taxonomy, Instance.from_xml(bad))
        tax_source = self.taxonomy_text.replace('from="m:Revenue"',
                        'xmlns:m="urn:other" xmlns:q="urn:lab" from="q:Revenue"', 1)
        # The to-QName on the same arc also belongs to the changed scope.
        with self.assertRaises(InputError):
            Taxonomy.from_xml(tax_source)
        tax_source = tax_source.replace('to="m:WideCube"', 'to="q:WideCube"', 1)
        scoped = Taxonomy.from_xml(tax_source)
        self.assertTrue(scoped.qualifies('{urn:lab}Revenue', {'{urn:lab}Region': '{urn:lab}North'}, {}))

    def test_duration_decimal_and_forward_references(self):
        source = self.batch([('precise', 'Revenue', 'north', '-0.1250')])
        source = source.replace('<xbrli:instant>2026-10-31</xbrli:instant>',
                                '<xbrli:startDate>2026-10-01</xbrli:startDate><xbrli:endDate>2026-10-31</xbrli:endDate>')
        start = source.index('<m:Revenue id="precise"')
        end = source.index('</m:Revenue>', start) + len('</m:Revenue>')
        fact = source[start:end]
        source = source[:start] + source[end:]
        position = source.index('>') + 1
        source = source[:position] + fact + source[position:]
        self.store.ingest('lab', 'precise', self.taxonomy, Instance.from_xml(source))
        row = self.store.read('lab')[0]
        self.assertEqual(row['value'], '-0.1250')
        self.assertEqual(row['period'], 'duration:2026-10-01/2026-10-31')

    def test_input_errors_do_not_change_existing_results(self):
        self.store.ingest('lab', 'initial', self.taxonomy, self.good)
        before = self.snapshot()
        source = self.accepted_text
        mutations = [source[:-12], '<!DOCTYPE x [<!ENTITY y "z">]>' + source,
                     source.replace('contextRef="north"', 'contextRef="absent"', 1),
                     source.replace('id="a"', 'id="b"', 1),
                     source.replace('>10</m:Revenue>', '>NaN</m:Revenue>', 1),
                     source.replace('dimension="m:Region"', 'dimension="unbound:Region"', 1),
                     source.replace('2026-10-31', '2026-02-30', 1)]
        member = '<xbrldi:explicitMember dimension="m:Region">m:North</xbrldi:explicitMember>'
        mutations.append(source.replace(member, member + member, 1))
        for bad in mutations:
            with self.subTest(xml=bad[:70]), self.assertRaises(InputError):
                self.store.ingest('lab', 'bad', self.taxonomy, Instance.from_xml(bad))
            self.assertEqual(self.snapshot(), before)
        unknown = Instance.from_xml(self.batch([('unknown', 'NotDeclared', 'north', '1')]))
        with self.assertRaises(InputError):
            self.store.ingest('lab', 'unknown', self.taxonomy, unknown)
        self.assertEqual(self.snapshot(), before)

    def test_taxonomy_rejects_ambiguous_or_invalid_relationships(self):
        source = self.taxonomy_text
        arc = '<arc kind="dimension-default" role="defaults" from="m:Channel" to="m:Wholesale"/>'
        invalid = [source.replace('</taxonomy>', arc + '</taxonomy>'),
                   source.replace('closed="true"', 'closed="yes"', 1),
                   source.replace('to="m:WideCube"', 'to="m:North"', 1),
                   source.replace('name="m:Revenue"', 'name="missing:Revenue"', 1)]
        for bad in invalid:
            with self.subTest(xml=bad[:70]), self.assertRaises(InputError):
                Taxonomy.from_xml(bad)
