"""Parse and evaluate the SOC ``preReqNotes`` strings.

Real examples from the API:

    (01:198:112 DATA STRUCTURES )<em> OR </em>(14:332:351 PROGRM METHODOLOGYII )
    ((01:198:205 ... or 14:332:312 ... ) and (01:640:152 CALCULUS II ...))<em> OR </em> (...)
    Any Course EQUAL or GREATER Than: (01:640:112 PRECALCULUS PART II )
    (01:640:244 DIFFERENTIAL EQUATIONS FOR ENGINEERING  AND PHYSICS  and 01:640:300 ...)

Course titles are free text and can contain "AND"/"OR", so an operator only
counts when it's followed by a course code or an opening parenthesis.
AND binds tighter than OR.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Union

from .courses import CODE_RE

TOKEN_RE = re.compile(r"\(|\)|\d{2}:\d{3}:\d{3}|\band\b|\bor\b|[^\s()]+", re.I)
AT_LEAST_RE = re.compile(r"any course equal or greater than\s*:?", re.I)


@dataclass
class Course:
    code: str
    or_higher: bool = False   # "Any Course EQUAL or GREATER Than"


@dataclass
class Op:
    op: str                    # "and" | "or"
    children: list["Node"] = field(default_factory=list)


Node = Union[Course, Op, None]


def _tokens(text: str) -> list[str]:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    at_least = bool(AT_LEAST_RE.search(text))
    text = AT_LEAST_RE.sub(" ", text)
    raw = TOKEN_RE.findall(text)
    out: list[str] = []
    for i, tok in enumerate(raw):
        low = tok.lower()
        if tok in "()" or CODE_RE.fullmatch(tok):
            out.append(tok if not CODE_RE.fullmatch(tok) else ("@" + tok if at_least else tok))
        elif low in ("and", "or"):
            nxt = raw[i + 1] if i + 1 < len(raw) else ""
            if nxt == "(" or CODE_RE.fullmatch(nxt):
                out.append(low)
        # everything else is title text -> dropped
    return out


class _Parser:
    def __init__(self, tokens: list[str]):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse_or(self) -> Node:
        items = [self.parse_and()]
        while self.peek() == "or":
            self.take()
            items.append(self.parse_and())
        return _make("or", items)

    def parse_and(self) -> Node:
        items = [self.parse_atom()]
        while self.peek() == "and":
            self.take()
            items.append(self.parse_atom())
        return _make("and", items)

    def parse_atom(self) -> Node:
        tok = self.take()
        if tok == "(":
            node = self.parse_or()
            if self.peek() == ")":
                self.take()
            return node
        if tok and tok.lstrip("@") and CODE_RE.fullmatch(tok.lstrip("@")):
            return Course(tok.lstrip("@"), or_higher=tok.startswith("@"))
        return None


def _make(op: str, items: list[Node]) -> Node:
    flat: list[Node] = []
    seen: set[str] = set()
    for it in items:
        if it is None:
            continue
        if isinstance(it, Op) and it.op == op:
            flat.extend(it.children)
        elif isinstance(it, Course):
            key = f"{it.code}{it.or_higher}"
            if key not in seen:      # the SOC repeats codes ("152 and 152")
                seen.add(key)
                flat.append(it)
        else:
            flat.append(it)
    if not flat:
        return None
    if len(flat) == 1:
        return flat[0]
    return Op(op, flat)


def parse(text: str) -> Node:
    tokens = _tokens(text)
    if not tokens:
        return None
    return _Parser(tokens).parse_or()


def _course_ok(c: Course, has: Callable[[str], bool], taken: Iterable[str]) -> bool:
    if has(c.code):
        return True
    if c.or_higher:
        subj, num = c.code.rsplit(":", 1)
        return any(t.startswith(subj + ":") and t.rsplit(":", 1)[1][:3].isdigit()
                   and int(t.rsplit(":", 1)[1][:3]) >= int(num[:3]) for t in taken)
    return False


def satisfied(node: Node, taken: Iterable[str], has: Callable[[str], bool] | None = None) -> bool:
    """Evaluate a prerequisite tree against the set of course codes you've passed."""
    taken = set(taken)
    has = has or (lambda code: code in taken)
    if node is None:
        return True
    if isinstance(node, Course):
        return _course_ok(node, has, taken)
    results = (satisfied(ch, taken, has) for ch in node.children)
    return all(results) if node.op == "and" else any(results)


def to_text(node: Node) -> str:
    if node is None:
        return "none"
    if isinstance(node, Course):
        return node.code + ("+" if node.or_higher else "")
    inner = f" {node.op.upper()} ".join(
        to_text(c) if isinstance(c, Course) else f"({to_text(c)})" for c in node.children)
    return inner


def codes(node: Node) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, Course):
        return {node.code}
    out: set[str] = set()
    for c in node.children:
        out |= codes(c)
    return out
