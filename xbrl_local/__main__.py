import argparse
from dataclasses import asdict
import json
import sys
import sqlite3
from . import Taxonomy, Instance, Warehouse, InputError, QualificationError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Import a complete local explicit-dimension batch')
    parser.add_argument('--db', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    ingest = commands.add_parser('import')
    ingest.add_argument('--dataset', required=True)
    ingest.add_argument('--batch', required=True)
    ingest.add_argument('--taxonomy', required=True)
    ingest.add_argument('--instance', required=True)
    read = commands.add_parser('read')
    read.add_argument('--dataset', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'import':
            taxonomy = Taxonomy.from_file(args.taxonomy)
            instance = Instance.from_file(args.instance)
        with Warehouse(args.db) as warehouse:
            if args.command == 'import':
                result = asdict(warehouse.ingest(args.dataset, args.batch, taxonomy, instance))
            else:
                result = warehouse.read(args.dataset)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (InputError, OSError, sqlite3.Error) as exc:
        result = {'error': str(exc)}
        if isinstance(exc, QualificationError):
            result['issues'] = [asdict(issue) for issue in exc.issues]
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == '__main__':
    sys.exit(main())
