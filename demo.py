"""Exercise actual XML ingestion, rejection, replay and disk reopening."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import samples
from xbrl_local import Taxonomy, Instance, Warehouse, QualificationError, CalculationError


def main():
    taxonomy = Taxonomy.from_file(samples.ROOT / 'examples' / 'taxonomy.xml')
    with tempfile.TemporaryDirectory(prefix='local-xbrl-demo-') as directory:
        path = Path(directory) / 'warehouse.sqlite'
        good = Instance.from_file(samples.ROOT / 'examples' / 'accepted.xml')
        with Warehouse(path) as warehouse:
            receipt = warehouse.ingest('lab', 'initial', taxonomy, good)
            before = warehouse.read('lab')
            rejected = []
            try:
                warehouse.ingest('lab', 'rejected', taxonomy,
                                 Instance.from_file(samples.ROOT / 'examples' / 'rejected.xml'))
            except QualificationError as exc:
                rejected = [asdict(issue) for issue in exc.issues]
            assert len(rejected) == 6
            assert warehouse.read('lab') == before
            assert warehouse.ingest('lab', 'initial', taxonomy, good) == receipt
        with Warehouse(path) as reopened:
            assert reopened.read('lab') == before
            output = {'receipt': asdict(receipt), 'accepted': reopened.read('lab'),
                      'rejected': rejected, 'receipts': [asdict(r) for r in reopened.receipts('lab')]}
        calc_taxonomy = Taxonomy.from_file(samples.ROOT / 'examples' / 'calculation-taxonomy.xml')
        first = Instance.from_file(samples.ROOT / 'examples' / 'calculation-first.xml')
        second = Instance.from_file(samples.ROOT / 'examples' / 'calculation-second.xml')
        other = Instance.from_file(samples.ROOT / 'examples' / 'calculation-other-period.xml')
        with Warehouse(path) as warehouse:
            first_receipt = warehouse.ingest('calc', 'first', calc_taxonomy, first)
            assert first_receipt.inserted == 2
            groups = None
            try:
                warehouse.ingest('calc', 'second', calc_taxonomy, second)
            except CalculationError as exc:
                groups = exc.groups
            assert groups is not None
            facts_after = warehouse.read('calc')
            receipts_after = warehouse.receipts('calc')
            assert [row['id'] for row in facts_after] == ['p', 'x']
            assert [r.batch_id for r in receipts_after] == ['first']
            second_receipt = warehouse.ingest('calc', 'second', calc_taxonomy, other)
            assert second_receipt.inserted == 1
        with Warehouse(path) as reopened:
            final_facts = reopened.read('calc')
            final_receipts = reopened.receipts('calc')
            assert [row['id'] for row in final_facts] == ['p', 'q', 'x']
            assert [r.batch_id for r in final_receipts] == ['first', 'second']
        output['calculation'] = {
            'first': asdict(first_receipt),
            'jointly_rejected_groups': groups,
            'facts_after_rejection': facts_after,
            'receipts_after_rejection': [asdict(r) for r in receipts_after],
            'second': asdict(second_receipt),
            'reopened_facts': final_facts,
            'reopened_receipts': [asdict(r) for r in final_receipts]}
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
