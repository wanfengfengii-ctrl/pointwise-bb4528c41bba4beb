"""Namespace scopes belong to elements, including QName-valued attributes."""
import io
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from .errors import InputError

T = 'urn:local-xbrl:1'
I = 'http://www.xbrl.org/2003/instance'
D = 'http://xbrl.org/2006/xbrldi'
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*\Z')


def tag(ns, local):
    return '{' + ns + '}' + local


def parse(text, root_tag):
    if not isinstance(text, str) or re.search(r'<!\s*(DOCTYPE|ENTITY)', text, re.I):
        raise InputError('XML must be text without a DTD or entity declarations')
    scopes, stack, pending = {}, [], []
    try:
        parser = ET.iterparse(io.StringIO(text), events=('start-ns', 'start', 'end'))
        for event, obj in parser:
            if event == 'start-ns':
                pending.append(obj)
            elif event == 'start':
                scope = dict(stack[-1]) if stack else {}
                scope.update(pending)
                pending.clear()
                scopes[obj] = scope
                stack.append(scope)
            else:
                stack.pop()
        root = parser.root
    except ET.ParseError as exc:
        raise InputError('malformed XML') from exc
    if root.tag != root_tag:
        raise InputError('unexpected XML root')
    return root, scopes


def qname(value, element, scopes):
    value = (value or '').strip()
    pieces = value.split(':')
    if len(pieces) == 1:
        prefix, local = '', pieces[0]
    elif len(pieces) == 2:
        prefix, local = pieces
        if not _NAME.fullmatch(prefix):
            raise InputError('invalid QName prefix')
    else:
        raise InputError('invalid QName')
    if not _NAME.fullmatch(local):
        raise InputError('invalid QName local name')
    uri = scopes[element].get(prefix)
    if uri is None or not uri:
        raise InputError('unbound QName namespace')
    return tag(uri, local)


def required(element, attribute):
    value = element.get(attribute, '').strip()
    if not value:
        raise InputError('missing ' + attribute)
    return value


def boolean(element, attribute, default):
    value = element.get(attribute)
    if value is None:
        return default
    if value not in ('true', 'false'):
        raise InputError('invalid boolean ' + attribute)
    return value == 'true'


def read_xml(path):
    try:
        return Path(path).read_bytes().decode('utf-8')
    except UnicodeError as exc:
        raise InputError('XML files must be UTF-8') from exc
