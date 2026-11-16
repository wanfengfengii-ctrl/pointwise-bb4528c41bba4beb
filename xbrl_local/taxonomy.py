"""Finite explicit-dimension relationship package interpreter."""
from collections import defaultdict
from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from .errors import InputError
from .xmlio import T, tag, parse, qname, required, boolean, read_xml


@dataclass(frozen=True)
class Arc:
    kind: str
    role: str
    source: str
    target: str
    next_role: str
    usable: bool
    closed: bool
    part: str


@dataclass(frozen=True)
class CubeCondition:
    cube: str
    positive: bool
    closed: bool
    part: str
    dimensions: tuple

    def matches(self, parts, defaults):
        supplied = parts[self.part]
        names = {name for name, allowed in self.dimensions}
        if self.closed and set(supplied) - names:
            return False
        return all(supplied.get(name, defaults.get(name)) in allowed
                   for name, allowed in self.dimensions)


@dataclass(frozen=True)
class RoleConditions:
    role: str
    cubes: tuple


class Taxonomy:
    @classmethod
    def from_file(cls, path):
        return cls.from_xml(read_xml(path))

    @classmethod
    def from_xml(cls, text):
        root, scopes = parse(text, tag(T, 'taxonomy'))
        kinds, arcs, defaults = {}, [], {}
        for element in root:
            if element.tag == tag(T, 'concept'):
                name = qname(required(element, 'name'), element, scopes)
                kind = required(element, 'kind')
                if name in kinds or kind not in ('metric', 'cube', 'dimension', 'member'):
                    raise InputError('duplicate concept or unknown kind')
                kinds[name] = kind
            elif element.tag != tag(T, 'arc'):
                raise InputError('unknown taxonomy element')
        types = {'all': ('metric', 'cube'), 'notAll': ('metric', 'cube'),
                 'hypercube-dimension': ('cube', 'dimension'),
                 'dimension-domain': ('dimension', 'member'),
                 'domain-member': ('member', 'member'),
                 'dimension-default': ('dimension', 'member')}
        seen = set()
        for element in root.findall(tag(T, 'arc')):
            kind, role = required(element, 'kind'), required(element, 'role')
            source = qname(required(element, 'from'), element, scopes)
            target = qname(required(element, 'to'), element, scopes)
            if kind not in types or (kinds.get(source), kinds.get(target)) != types[kind]:
                raise InputError('invalid relationship endpoints')
            next_role = element.get('targetRole', role).strip()
            part = element.get('contextElement', 'segment')
            if not next_role or part not in ('segment', 'scenario'):
                raise InputError('invalid targetRole or contextElement')
            allowed = {'kind', 'role', 'from', 'to', 'targetRole'}
            if kind in ('all', 'notAll'):
                allowed.update(('closed', 'contextElement'))
            if kind in ('dimension-domain', 'domain-member'):
                allowed.add('usable')
            if set(element.attrib) - allowed:
                raise InputError('unsupported relationship attribute')
            if kind == 'dimension-default' and 'targetRole' in element.attrib:
                raise InputError('defaults are global and cannot switch role')
            arc = Arc(kind, role, source, target, next_role,
                      boolean(element, 'usable', True), boolean(element, 'closed', False), part)
            if arc in seen:
                raise InputError('duplicate relationship')
            seen.add(arc)
            arcs.append(arc)
            if kind == 'dimension-default':
                if source in defaults:
                    raise InputError('multiple defaults for dimension')
                defaults[source] = target
        obj = cls()
        obj.kinds = MappingProxyType(kinds)
        obj.defaults = MappingProxyType(defaults)
        obj.digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        index = defaultdict(list)
        for arc in arcs:
            index[arc.kind, arc.role, arc.source].append(arc)
        obj._index = {key: tuple(value) for key, value in index.items()}
        rules = {}
        for metric, kind in kinds.items():
            if kind != 'metric':
                continue
            groups = defaultdict(list)
            for arc in arcs:
                if arc.source == metric and arc.kind in ('all', 'notAll'):
                    dimensions = defaultdict(set)
                    for hd in obj._edges('hypercube-dimension', arc.next_role, arc.target):
                        dimensions[hd.target].update(obj._members(hd.target, hd.next_role))
                    groups[arc.role].append(CubeCondition(
                        arc.target, arc.kind == 'all', arc.closed, arc.part,
                        tuple((d, frozenset(m)) for d, m in sorted(dimensions.items()))))
            rules[metric] = tuple(RoleConditions(r, tuple(c)) for r, c in sorted(groups.items()))
        obj._rules = rules
        return obj

    def _edges(self, kind, role, source):
        return self._index.get((kind, role, source), ())

    def _members(self, dimension, role):
        allowed, visited = set(), set()
        pending = list(self._edges('dimension-domain', role, dimension))
        while pending:
            arc = pending.pop()
            if arc.usable:
                allowed.add(arc.target)
            state = (arc.next_role, arc.target)
            if state not in visited:
                visited.add(state)
                pending.extend(self._edges('domain-member', *state))
        return allowed

    def rules_for(self, metric):
        if self.kinds.get(metric) != 'metric':
            raise InputError('unknown metric ' + metric)
        return self._rules[metric]

    def qualifies(self, metric, segment, scenario):
        groups = self.rules_for(metric)
        parts = {'segment': segment, 'scenario': scenario}
        for supplied in parts.values():
            for dimension, member in supplied.items():
                if self.kinds.get(dimension) != 'dimension' or self.kinds.get(member) != 'member':
                    return False
                if self.defaults.get(dimension) == member:
                    return False
        if not groups:
            return not segment and not scenario
        return any(all(c.matches(parts, self.defaults) == c.positive for c in group.cubes)
                   for group in groups)
