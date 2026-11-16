"""Finite local examples shared by the demo and business regressions."""
from pathlib import Path
import re
from xml.sax.saxutils import quoteattr, escape

ROOT = Path(__file__).resolve().parent


def taxonomy_xml():
    return (ROOT / 'examples' / 'taxonomy.xml').read_text(encoding='utf-8')


def accepted_xml():
    return (ROOT / 'examples' / 'accepted.xml').read_text(encoding='utf-8')


def rejected_xml():
    return (ROOT / 'examples' / 'rejected.xml').read_text(encoding='utf-8')


def batch(rows, template=None):
    # Each row is (fact id, local metric name, context id, decimal text).
    head = (accepted_xml() if template is None else template).split('<!-- facts -->', 1)[0]
    facts = []
    for identity, metric, context, value in rows:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', metric):
            raise ValueError('sample metric must be a local name')
        facts.append('<m:' + metric + ' id=' + quoteattr(identity) +
                     ' contextRef=' + quoteattr(context) +
                     ' unitRef="usd" decimals="0">' + escape(value) + '</m:' + metric + '>')
    return head + ''.join(facts) + '</xbrli:xbrl>'
