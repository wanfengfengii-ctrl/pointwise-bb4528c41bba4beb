"""Read the supported local numeric XBRL instance subset."""
from dataclasses import dataclass
from datetime import date
import re
from types import MappingProxyType
from .errors import InputError
from .xmlio import I, D, tag, parse, qname, required, read_xml


def _only(element, allowed):
    if any(child.tag not in allowed for child in element):
        raise InputError('unsupported instance element')


def _one(element, name):
    found = element.findall(name)
    if len(found) != 1:
        raise InputError('expected one ' + name)
    return found[0]


def _text(element):
    if len(element) or not (element.text or '').strip():
        raise InputError('expected nonempty leaf text')
    return element.text.strip()


def _day(element):
    value = _text(element)
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError as exc:
        raise InputError('invalid ISO date') from exc
    return value


@dataclass(frozen=True)
class Context:
    id: str
    scheme: str
    entity: str
    period: str
    segment: tuple
    scenario: tuple


@dataclass(frozen=True)
class Fact:
    id: str
    metric: str
    context_id: str
    unit: str
    value: str
    decimals: str


@dataclass(frozen=True)
class Instance:
    contexts: object
    facts: tuple

    @classmethod
    def from_file(cls, path):
        return cls.from_xml(read_xml(path))

    @classmethod
    def from_xml(cls, text):
        root, scopes = parse(text, tag(I, 'xbrl'))
        contexts, units, ids = {}, {}, set()
        for element in root:
            identity = required(element, 'id')
            if identity in ids:
                raise InputError('duplicate XML id ' + identity)
            ids.add(identity)
            if element.tag == tag(I, 'context'):
                _only(element, {tag(I, 'entity'), tag(I, 'period'), tag(I, 'scenario')})
                entity = _one(element, tag(I, 'entity'))
                _only(entity, {tag(I, 'identifier'), tag(I, 'segment')})
                identifier = _one(entity, tag(I, 'identifier'))
                scheme, name = required(identifier, 'scheme'), _text(identifier)
                period = _one(element, tag(I, 'period'))
                _only(period, {tag(I, 'instant'), tag(I, 'startDate'), tag(I, 'endDate')})
                if len(period) == 1 and period[0].tag == tag(I, 'instant'):
                    time = 'instant:' + _day(period[0])
                elif len(period) == 2 and {c.tag for c in period} == {tag(I, 'startDate'), tag(I, 'endDate')}:
                    start = _day(_one(period, tag(I, 'startDate')))
                    end = _day(_one(period, tag(I, 'endDate')))
                    if start > end:
                        raise InputError('reversed period')
                    time = 'duration:' + start + '/' + end
                else:
                    raise InputError('unsupported period')
                parts = []
                for parent, part in ((entity, 'segment'), (element, 'scenario')):
                    containers = parent.findall(tag(I, part))
                    if len(containers) > 1:
                        raise InputError('duplicate context container')
                    members = {}
                    if containers:
                        _only(containers[0], {tag(D, 'explicitMember')})
                        for member in containers[0]:
                            dimension = qname(required(member, 'dimension'), member, scopes)
                            if dimension in members:
                                raise InputError('duplicate explicit dimension')
                            members[dimension] = qname(_text(member), member, scopes)
                    parts.append(tuple(sorted(members.items())))
                if set(dict(parts[0])) & set(dict(parts[1])):
                    raise InputError('dimension repeated across context containers')
                contexts[identity] = Context(identity, scheme, name, time, *parts)
            elif element.tag == tag(I, 'unit'):
                _only(element, {tag(I, 'measure')})
                measure = _one(element, tag(I, 'measure'))
                units[identity] = qname(_text(measure), measure, scopes)
        facts = []
        for element in root:
            if element.tag in (tag(I, 'context'), tag(I, 'unit')):
                continue
            if not element.tag.startswith('{') or element.tag.startswith('{' + I + '}'):
                raise InputError('unsupported fact element')
            if set(element.attrib) - {'id', 'contextRef', 'unitRef', 'decimals'}:
                raise InputError('unsupported fact attribute')
            identity = required(element, 'id')
            context = required(element, 'contextRef')
            unit = required(element, 'unitRef')
            value = _text(element)
            decimals = element.get('decimals', 'INF')
            if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', value):
                raise InputError('expected finite decimal fact')
            if decimals != 'INF' and not re.fullmatch(r'[+-]?[0-9]+', decimals):
                raise InputError('invalid decimals')
            if context not in contexts or unit not in units:
                raise InputError('unresolved context or unit')
            facts.append(Fact(identity, element.tag, context, units[unit], value, decimals))
        if not facts:
            raise InputError('empty fact batch')
        return cls(MappingProxyType(contexts), tuple(facts))
