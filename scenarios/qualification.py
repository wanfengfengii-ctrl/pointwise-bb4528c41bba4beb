"""Small, independently enumerated business acceptance matrix."""
from pathlib import Path
import json
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import samples
from xbrl_local import Taxonomy, Instance, Warehouse, QualificationError

CONTEXTS = ('north', 'south', 'forbidden', 'shared', 'hidden', 'root', 'empty',
            'extra', 'wholesale', 'explicit_default', 'scenario', 'south_scenario', 'wrong_member')
# These literal sets are business expectations, not computed from relationships.
ACCEPTED = {
    'Revenue': {'north', 'south', 'shared', 'wholesale'},
    'Expense': {'south'},
    'Combined': {'south'},
    'Alternative': {'north', 'south', 'forbidden', 'shared', 'wholesale'},
    'OpenMetric': {'north', 'south', 'forbidden', 'shared', 'extra', 'wholesale'},
    'ScenarioMetric': {'scenario'},
    'Bare': {'empty'},
}


def run(taxonomy_text=None, template_text=None):
    taxonomy = Taxonomy.from_xml(samples.taxonomy_xml() if taxonomy_text is None else taxonomy_text)
    def make_batch(rows):
        return samples.batch(rows, template_text)
    actual, expected = [], []
    with Warehouse() as warehouse:
        for metric, allowed in ACCEPTED.items():
            for context in CONTEXTS:
                identity = metric + '-' + context
                instance = Instance.from_xml(make_batch([(identity, metric, context, '10')]))
                before = (warehouse.read('matrix'), warehouse.receipts('matrix'))
                try:
                    warehouse.ingest('matrix', identity, taxonomy, instance)
                except QualificationError as exc:
                    if [issue.fact_id for issue in exc.issues] != [identity]:
                        raise AssertionError('DIMENSION_QUALIFICATION_MISMATCH: error identity')
                    if (warehouse.read('matrix'), warehouse.receipts('matrix')) != before:
                        raise AssertionError('DIMENSION_QUALIFICATION_MISMATCH: failed batch changed data')
                else:
                    actual.append(identity)
                if context in allowed:
                    expected.append(identity)
        if sorted(actual) != sorted(expected):
            raise AssertionError('DIMENSION_QUALIFICATION_MISMATCH: ' + repr((expected, actual)))
        if [row['id'] for row in warehouse.read('matrix')] != sorted(expected):
            raise AssertionError('DIMENSION_QUALIFICATION_MISMATCH: stored set')
        before = (warehouse.read('matrix'), warehouse.receipts('matrix'))
        for pair in ((('a', 'Revenue'), ('b', 'Expense')), (('b', 'Expense'), ('a', 'Revenue'))):
            instance = Instance.from_xml(make_batch([(i, m, 'north', '10') for i, m in pair]))
            try:
                warehouse.ingest('matrix', 'mixed', taxonomy, instance)
            except QualificationError as exc:
                if [issue.fact_id for issue in exc.issues] != ['b']:
                    raise AssertionError('DIMENSION_QUALIFICATION_MISMATCH: shared context')
            else:
                raise AssertionError('DIMENSION_QUALIFICATION_MISMATCH: mixed batch accepted')
            if (warehouse.read('matrix'), warehouse.receipts('matrix')) != before:
                raise AssertionError('DIMENSION_QUALIFICATION_MISMATCH: mixed batch changed data')
    return {'checked': len(CONTEXTS) * len(ACCEPTED), 'accepted': sorted(expected), 'mixed_orders': 2}


if __name__ == '__main__':
    print(json.dumps(run(), sort_keys=True))
