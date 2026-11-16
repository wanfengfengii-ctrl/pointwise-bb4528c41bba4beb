"""Plain XML fixtures for the calculation extension; no constraint solver."""
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from xbrl_local import Instance

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / 'examples'


def instance_xml(rows, *, day='2026-10-31', context_id='c', unit_id='u'):
    """rows: (fact ID, local metric name, numeric text, decimals text)."""
    facts = []
    for identity, metric, value, decimals in rows:
        if metric not in ('X', 'P', 'Q', 'Y', 'A', 'B', 'C', 'D'):
            raise ValueError('fixture metric outside the finite sample vocabulary')
        facts.append('<m:' + metric + ' id=' + quoteattr(identity) +
                     ' contextRef=' + quoteattr(context_id) +
                     ' unitRef=' + quoteattr(unit_id) +
                     ' decimals=' + quoteattr(decimals) + '>' +
                     escape(value) + '</m:' + metric + '>')
    return ('<i:xbrl xmlns:i="http://www.xbrl.org/2003/instance" '
            'xmlns:m="urn:calculation" xmlns:u="urn:calculation:unit">' +
            '<i:context id=' + quoteattr(context_id) +
            '><i:entity><i:identifier scheme="urn:calculation:entity">E</i:identifier>'
            '</i:entity><i:period><i:instant>' + escape(day) +
            '</i:instant></i:period></i:context><i:unit id=' + quoteattr(unit_id) +
            '><i:measure>u:count</i:measure></i:unit>' +
            ''.join(facts) + '</i:xbrl>\n')


def check():
    first = Instance.from_file(EXAMPLES / 'calculation-first.xml')
    second = Instance.from_file(EXAMPLES / 'calculation-second.xml')
    other = Instance.from_file(EXAMPLES / 'calculation-other-period.xml')
    assert [(f.id, f.metric, f.value, f.decimals) for f in first.facts] == [
        ('x', '{urn:calculation}X', '0.5', '0'),
        ('p', '{urn:calculation}P', '0', 'INF')]
    assert [(f.id, f.value, f.decimals) for f in second.facts] == [('q', '1', 'INF')]
    a, b, c = (next(iter(i.contexts.values())) for i in (first, second, other))
    assert a.id != b.id and a.period == b.period and a.period != c.period
    assert (a.scheme, a.entity, a.segment, a.scenario) == (
        b.scheme, b.entity, b.segment, b.scenario)
    assert first.facts[0].unit == second.facts[0].unit
    generated = Instance.from_xml(instance_xml([('n', 'Y', '-1.50', '-1')]))
    assert generated.facts[0].value == '-1.50'
    assert generated.facts[0].decimals == '-1'
    return {'fixtures': 3, 'first_ids': [f.id for f in first.facts],
            'second_ids': [f.id for f in second.facts],
            'periods': [a.period, c.period]}


if __name__ == '__main__':
    import json
    print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
