"""Append-only fact identities and batch receipts in one SQLite transaction."""
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from .calculation import inconsistent_groups
from .errors import InputError, ConflictError, QualificationError, Issue, CalculationError


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class Receipt:
    dataset: str
    batch_id: str
    inserted: int


class Warehouse:
    def __init__(self, path=':memory:'):
        self._db = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        version = self._db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self._db.close()
            raise InputError('unsupported warehouse version')
        self._db.execute('PRAGMA foreign_keys=ON')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS datasets(
                name TEXT PRIMARY KEY, taxonomy TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS facts(
                dataset TEXT NOT NULL REFERENCES datasets(name),
                fact_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(dataset, fact_id));
            CREATE TABLE IF NOT EXISTS batches(
                dataset TEXT NOT NULL REFERENCES datasets(name),
                batch_id TEXT NOT NULL, fingerprint TEXT NOT NULL, inserted INTEGER NOT NULL,
                PRIMARY KEY(dataset, batch_id));
            PRAGMA user_version=1;
        ''')

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def ingest(self, dataset, batch_id, taxonomy, instance):
        if not isinstance(dataset, str) or not dataset.strip() or not isinstance(batch_id, str) or not batch_id.strip():
            raise InputError('dataset and batch_id must be nonempty strings')
        rows, issues, decisions = [], [], {}
        for fact in instance.facts:
            context = instance.contexts[fact.context_id]
            key = (fact.metric, context)
            if key not in decisions:
                decisions[key] = taxonomy.qualifies(fact.metric, dict(context.segment), dict(context.scenario))
            if not decisions[key]:
                issues.append(Issue(fact.id, fact.metric, fact.context_id))
            rows.append({'id': fact.id, 'metric': fact.metric, 'context_id': context.id,
                         'entity': {'scheme': context.scheme, 'identifier': context.entity},
                         'period': context.period,
                         'dimensions': {'segment': dict(context.segment), 'scenario': dict(context.scenario)},
                         'unit': fact.unit, 'value': fact.value, 'decimals': fact.decimals})
        if issues:
            raise QualificationError(issues)
        rows.sort(key=lambda row: row['id'])
        fingerprint = hashlib.sha256(_json([taxonomy.digest, rows]).encode('utf-8')).hexdigest()
        db = self._db
        db.execute('BEGIN IMMEDIATE')
        try:
            prior = db.execute('SELECT fingerprint, inserted FROM batches WHERE dataset=? AND batch_id=?',
                               (dataset, batch_id)).fetchone()
            if prior is not None:
                if prior[0] != fingerprint:
                    raise ConflictError('batch identity reused with different content')
                result = Receipt(dataset, batch_id, prior[1])
            else:
                pinned = db.execute('SELECT taxonomy FROM datasets WHERE name=?', (dataset,)).fetchone()
                if pinned is not None and pinned[0] != taxonomy.digest:
                    raise ConflictError('dataset taxonomy differs')
                db.execute('INSERT OR IGNORE INTO datasets VALUES (?, ?)', (dataset, taxonomy.digest))
                inserted = 0
                for row in rows:
                    payload = _json(row)
                    old = db.execute('SELECT payload FROM facts WHERE dataset=? AND fact_id=?',
                                     (dataset, row['id'])).fetchone()
                    if old is not None:
                        if old[0] != payload:
                            raise ConflictError('fact identity conflict: ' + row['id'])
                    else:
                        db.execute('INSERT INTO facts VALUES (?, ?, ?)', (dataset, row['id'], payload))
                        inserted += 1
                if taxonomy.calculations:
                    stored = [json.loads(record[0]) for record in db.execute(
                        'SELECT payload FROM facts WHERE dataset=?', (dataset,))]
                    groups = inconsistent_groups(taxonomy, stored)
                    if groups:
                        raise CalculationError(groups)
                db.execute('INSERT INTO batches VALUES (?, ?, ?, ?)', (dataset, batch_id, fingerprint, inserted))
                result = Receipt(dataset, batch_id, inserted)
            db.execute('COMMIT')
            return result
        except BaseException:
            db.execute('ROLLBACK')
            raise

    def read(self, dataset):
        return [json.loads(row[0]) for row in self._db.execute(
            'SELECT payload FROM facts WHERE dataset=? ORDER BY fact_id', (dataset,))]

    def receipts(self, dataset):
        return [Receipt(dataset, row[0], row[1]) for row in self._db.execute(
            'SELECT batch_id, inserted FROM batches WHERE dataset=? ORDER BY batch_id', (dataset,))]
