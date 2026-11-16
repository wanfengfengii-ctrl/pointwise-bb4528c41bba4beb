"""Exercise actual XML ingestion, rejection, replay and disk reopening."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import samples
from xbrl_local import Taxonomy, Instance, Warehouse, QualificationError


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
            print(json.dumps({'receipt': asdict(receipt), 'accepted': reopened.read('lab'),
                              'rejected': rejected, 'receipts': [asdict(r) for r in reopened.receipts('lab')]},
                             ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
