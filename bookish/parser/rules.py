# Copyright 2017 Matt Chaput. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#    1. Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#
#    2. Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY MATT CHAPUT ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO
# EVENT SHALL MATT CHAPUT OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are
# those of the authors and should not be interpreted as representing official
# policies, either expressed or implied, of Matt Chaput.

"""
This module defines the basic building blocks for a PEG parser.
"""

from __future__ import print_function
import inspect
import re
import sys
import time
from collections import defaultdict

from bookish.compat import string_type


class Miss:
    """
    This class serves as a "token" to be returned to indicate a rule did not
    match at the given position (it is not meant to be instantiated). This is
    a performance hack; returning a singleton is so much faster than using
    exceptions it's worth the convoluted un-Pythonic code.
    """

    def __init__(self):
        raise NotImplementedError


class Empty:
    """
    Rules always need to return a value. This class serves as a "token" to be
    returned when a match doesn't actually correspond to text at the given
    position (for example, a lookbehind match). This allows the system to
    distinguish textual matches that happen to be empty ('') from "virtual"
    matches.
    """

    def __init__(self):
        raise NotImplementedError


class Failure:
    """
    This class servers as a token to be returned by a FailIf rule inside a Mixed
    rule. Whereas "Miss" means "this rule did not match at the current position"
    this value means "this rule matched so the entire parent Mixed rule is a
    Miss".
    """

    def __init__(self):
        raise NotImplementedError


# Constants

# This regex matches one or more blank lines
emptylines_expr = re.compile("\n([ \t]*\n)+", re.MULTILINE)
# This regex matches a newline followed by an option indent
ws_expr = re.compile("\n( *)")
# This dictionary sets up a mapping between open and close bracket chars, so we
# know how to increment/decrement bracket counts when parsing Python expressions
brackets = {"(": ")", "[": "]", "{": "}"}
# This is a set containing the close brackets from the previous dictionary
endbrackets = frozenset(brackets.values())


# Helper functions

def ensure(rule):
    """
    Ensures an argument to a rule is itself a rule. Basically, lets you use a
    string value "x" and turn it into a String("x") rule automatically.
    """

    if isinstance(rule, string_type):
        rule = String(rule)
    if not isinstance(rule, Rule):
        raise ValueError("%r is not a Rule" % (rule, ))
    return rule


def compile_expr(expr):
    """
    Compiles a Python source code string into a Python expression code object.
    """

    return compile(expr, expr, 'eval', dont_inherit=True)


def make_firstmap(rules, pctx):
    """
    Given a list of rules, generates a mapping between initial characters and
    the rules that could match starting with that character. The None key maps
    to a list of rules that could match starting with any character.

    This is performance optimization. Figuring out what characters a rule can
    possibly start with, and only trying the rule if we're on one of those
    characters, gives a massive performance boost.
    """

    char2rules = defaultdict(list)
    for r in rules:
        firsts = r.first_chars(pctx)
        if firsts is None:
            char2rules[None].append(r)
        else:
            for char in firsts:
                char2rules[char].append(r)

    always = char2rules.get(None)
    if always:
        for key in char2rules:
            if key is not None:
                rs = char2rules[key] + always
                char2rules[key] = sorted(rs, key=lambda x: rules.index(x))
    else:
        char2rules[None] = ()

    char2rules = dict((char, rs) for char, rs in char2rules.items())
    return char2rules


def firstmap_string(builder, firstmap):
    """
    Returns a Python source code string representation of a dictionary as
    created by make_firstmap().
    """

    if firstmap:
        fmcode = "{\n"
        fmitems = sorted(firstmap.items(), key=lambda x: x[0] or '')
        for char, rlist in fmitems:
            if rlist:
                names = [builder.effective_name(r) for r in rlist]
                names = ", ".join(names)
                fmcode += "    %r: (%s,),\n" % (char, names)
            else:
                fmcode += "    %r: (),\n" % char
        fmcode += "}"
    else:
        fmcode = "None"
    return fmcode


def charset_string(chars):
    """
    Returns a Python source code representation of a set of characters.
    """

    return repr("".join(chars))


def take_python_expr(stream, i, ends):
    """
    Starting at a given position, takes a string corresponding to a Python
    expression, stopping when it sees one of the characters in the "ends" set.
    Returns None if there is not a valid Python expression at the given
    position.
    """

    start = i
    stack = []
    length = len(stream)
    if stream.endswith("\x03"):
        length -= 1

    while i < length:
        char = stream[i]

        # Check if we can end here
        if len(stack) == 0 and char in ends:
            break

        # If the char is an open bracket, add it to the stack
        if char in brackets:
            stack.append((brackets[char], i))
        # If it's the close bracket we're looking for, pop the stack
        elif stack and char == stack[-1][0]:
            stack.pop()
        # If it's a close bracket we're NOT looking for, no match
        elif char in endbrackets:
            return None, i

        # If we're starting a string, loop through chars until we find
        # the end quote
        if char in "\"'":
            while i < length - 1:
                i += 1
                inner = stream[i]
                if inner == "\\":
                    i += 1
                elif inner == char:
                    break

            if i >= length:
                return None, start

        # Move to the next char
        i += 1

    out = stream[start:i]
    if stack:
        ochar, opos = stack[-1]
        raise Exception("Unmatched %r at %s" % (ochar, opos))
    if not out:
        raise Exception("Empty Python expression")
    return out, i


def take_app_args(stream, i):
    """
    Starting at the given position, parses a string corresponding to a
    bracketed, space-separated list of arguments (e.g. "(a b 'c')") and returns
    a list of argument strings (e.g. ["a", "b", "'c'"]).
    """

    args = []
    length = len(stream)
    if stream.endswith("\x03"):
        length -= 1

    start = i
    while i < length:
        expr, i = take_python_expr(stream, i, ") ")
        if expr:
            args.append(expr)
        else:
            return None, start

        if stream[i] == ")":
            break
        elif stream[i] == " ":
            i += 1
        else:
            raise Exception("Unknown character at %s" %
                            (row_and_col(stream, i),))
    return args, i


def row_and_col(stream, i):
    """
    Given a string and an index into the string, returns a tuple of the line
    number and column number corresponding to that position.
    """

    length = len(stream)
    if stream.endswith("\x03"):
        length -= 1

    row = 1
    nl = stream.find("\n")
    while 0 <= nl < i < length:
        row += 1
        nl = stream.find("\n", nl + 1)

    pnl = stream.rfind("\n", 0, i)
    col = (i - pnl) if pnl >= 0 else i + 1

    return row, col


def name_rules(d):
    for name, value in d.items():
        if isinstance(value, Rule):
            value._rulename = name


# Rules

class Rule(object):
    """
    Base class for all rules.
    """

    _might_be_zero = True
    _fixedlen = None
    _rulename = None

    def __init__(self):
        pass

    def __repr__(self):
        typename = type(self).__name__
        rep = self.rulename() or self._repr()
        if rep:
            return "<%s %s>" % (typename, rep)
        else:
            return "<%s>" % typename

    def __add__(self, other):
        if isinstance(self, Seq) and isinstance(other, Seq):
            return Seq(*(self.rules + other.rules))
        elif isinstance(self, Seq):
            return Seq(*(self.rules + [ensure(other)]))
        elif isinstance(other, Seq):
            return Seq(self, *other.rules)
        else:
            return Seq(self, ensure(other))

    def __radd__(self, other):
        if isinstance(self, Seq):
            return Seq(ensure(other), *self.rules)
        else:
            return Seq(ensure(other), self)

    def __or__(self, other):
        if isinstance(self, Or) and isinstance(other, Or):
            return Or(*(self.rules + other.rules))
        elif isinstance(self, Or):
            return Or(*(self.rules + [ensure(other)]))
        elif isinstance(other, Or):
            return Or(self, *other.rules)
        else:
            return Or(self, ensure(other))

    def __ror__(self, other):
        if isinstance(self, Seq):
            return Seq(other, *self.rules)
        else:
            return Seq(ensure(other), self)

    def __pow__(self, name):
        self.set_name(name)
        return self

    def _repr(self):
        return

    def dump(self, pctx, level=0):
        print("  " * level, repr(self), self.first_chars(pctx), self.fixed_length())
        for child in self.children():
            if not isinstance(child, Rule):
                raise Exception("%r child %r is not a rule" % (self, child))
            child.dump(pctx, level + 1)

    def children(self):
        return ()

    def set_name(self, name):
        self._rulename = name
        return self

    def rulename(self):
        return self._rulename

    def fixed_length(self, pctx=None):
        return self._fixedlen

    def is_optional(self):
        return False

    def first_chars(self, pctx):
        return None

    def __call__(self, stream, i, context):
        raise NotImplementedError

    def accept(self, stream, i, context):
        if context.debug:
            print(" " * len(inspect.stack()), "%r %s %r" % (self, i, stream[i:i+20]))
        x = self(stream, i, context)
        if context.debug:
            if x[0] is Miss:
                print(" " * len(inspect.stack()), "MISS")
            else:
                print(" " * len(inspect.stack()), "<--", x)
        return x

    def has_binding(self, bld):
        return False

    def snap(self, pctx, seen):
        seen.add(self)
        return self

    def build(self, bld):
        raise NotImplementedError(type(self))


class SingletonRule(Rule):
    """
    Base class for rules which only ever have one instance.
    """

    def __hash__(self):
        return hash(self.__class__)


class Any(SingletonRule):
    """
    Matches any character.
    """

    _might_be_zero = False
    _fixedlen = 1
    inline = True

    @staticmethod
    def __call__(stream, i, context):
        if stream[i] == "\x03" or i >= len(stream):
            return Miss, None
        return stream[i], i + 1

    def build(self, bld):
        bld.line("if stream[i] == '\\x03' or i >= len(stream):")
        bld.line("    out = Miss")
        bld.line("else:")
        bld.line("    out = stream[i]")
        bld.line("    i += 1")


class AlphaNum(SingletonRule):
    """
    Matches any alphanumeric character.
    """

    _might_be_zero = False
    _fixedlen = 1
    inline = True

    @staticmethod
    def __call__(stream, i, context):
        if i >= len(stream) or not stream[i].isalnum():
            return Miss, None
        return stream[i], i + 1

    def build(self, bld):
        bld.line("if i >= len(stream) or not stream[i].isalnum():")
        bld.line("    out = Miss")
        bld.line("else:")
        bld.line("    out = stream[i]")
        bld.line("    i += 1")


class StreamStart(SingletonRule):
    """
    Matches at the start of the input.
    """

    _fixedlen = 0
    inline = True

    @staticmethod
    def __call__(stream, i, context):
        if i == 0:
            return Empty, i
        else:
            return Miss, None

    def build(self, bld):
        bld.line("if i == 0:")
        bld.line("    out = Empty")
        bld.line("else:")
        bld.line("    out = Miss")


class LineStart(SingletonRule):
    """
    Matches at the start of a line (so, at the start of the input, or right
    after a newline character).
    """

    _fixedlen = 0
    inline = True

    @staticmethod
    def __call__(stream, i, context):
        if i < len(stream) and (i == 0 or stream.startswith("\n", i - 1)):
            return Empty, i
        else:
            return Miss, None

    def build(self, bld):
        bld.line("if i < len(stream) and (i == 0 or stream.startswith('\\n', i - 1)):")
        bld.line("    out = Empty")
        bld.line("else:")
        bld.line("    out = Miss")


class LineEnd(SingletonRule):
    """
    Matches the end of a line (so, at the end of the input or a newline). Note
    that this rule consumes the newline.
    """

    _fixedlen = 0
    inline = True

    def first_chars(self, pctx):
        return "\x03\n"

    @staticmethod
    def __call__(stream, i, context):
        if stream.startswith("\x03", i) or i >= len(stream):
            return Empty, i
        elif stream.startswith("\n", i):
            return "\n", i + 1
        else:
            return Miss, None

    def build(self, bld):
        bld.line("if stream.startswith('\\x03', i) or i >= len(stream):")
        bld.line("    out = Empty")
        bld.line("elif stream.startswith('\\n', i):")
        bld.line("    out = '\\n'")
        bld.line("    i += 1")
        bld.line("else:")
        bld.line("    out = Miss")


class StreamEnd(SingletonRule):
    """
    Matches at the end of the input.
    """

    _fixedlen = 0
    inline = True

    def first_chars(self, pctx):
        return "\x03"

    @staticmethod
    def __call__(stream, i, context):
        if stream.startswith("\x03", i) or i >= len(stream):
            return Empty, i
        else:
            return Miss, None

    def build(self, bld):
        bld.line("if stream.startswith('\\x03', i) or i >= len(stream):")
        bld.line("    out = Empty")
        bld.line("else:")
        bld.line("    out = Miss")


class BlockBreak(SingletonRule):
    """
    Matches the end of a "block". So, the end of the input, or a newline
    followed by one or more blank lines, or a newline followed by a change in
    indentation. This is a specialized rule to encapsulate commonly desired wiki
    behavior without requiring the grammar author to define it manually.

    This rule sets the "indent" variable in the context to the indent of the new
    "block".
    """

    inline = True

    def first_chars(self, pctx):
        return "\x03\n"

    @staticmethod
    def __call__(stream, i, context):
        length = len(stream)
        if stream.endswith("\x03"):
            length -= 1

        # Consider the end of the stream to be a break
        if stream.startswith("\x03", i) or i >= length:
            return Empty, i

        # Only start checking if we're at a newline
        if stream.startswith("\n", i):
            # If this is the last newline in the file, it's a break
            if i + 1 == len(stream):
                return "\n", i + 1

            # If there are multiple newlines (possibly separated by whitespace),
            # it's a break
            m = emptylines_expr.match(stream, i)
            if m:
                return m.group(0), m.end()

            # If the newline is followed by spaces, we'll check if indentation
            # changed
            m = ws_expr.match(stream, i)
            if m:
                if m.end() == length:
                    return m.group(0), m.end()

                # Get the current indent from the context (the block rule should
                # have stored it)
                current_indent = (context.get("indent", 0) +
                                  context.get("bwidth", 0))
                # If the indentation after the newline does not equal the
                # current indentation, it's a break
                next_indent = len(m.group(1))
                if next_indent != current_indent:
                    return m.group(0), i + 1

        return Miss, None

    def build(self, bld):
        bld.line("out, i = rules.blockbreak(stream, i, context)")


# Make instances of the singleton rules. Other code should use these instead of
# instantiating the rules.
any_ = Any()
alphanum = AlphaNum()
streamstart = StreamStart()
linestart = LineStart()
lineend = LineEnd()
streamend = StreamEnd()
blockbreak = BlockBreak()


class Put(Rule):
    """
    Always matches, sets a value in the context.
    """

    _fixedlen = 0
    inline = True

    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __hash__(self):
        return hash((self.__class__, self.name, self.value))

    def _repr(self):
        return "%s=%s" % (self.name, self.value)

    def __call__(self, stream, i, context):
        context[self.name] = self.value
        return Empty, i

    def build(self, bld):
        bld.line("context[%r] = %r" % (self.name, self.value))
        bld.line("out = Empty")


class Get(Rule):
    """
    Always matches, outputs the value of a variable in the context.
    """

    _fixedlen = 0
    inline = True

    def __init__(self, name, default=None):
        self.name = name
        self.default = default

    def __hash__(self):
        return hash((self.__class__, self.name, self.default))

    def __call__(self, stream, i, context):
        return context.get(self.name, self.default), i

    def build(self, bld):
        bld.line("out = context.get(%r, %r)" % (self.name, self.default))


class Match(Rule):
    """
    Matches a given character.
    """

    _fixedlen = 1
    inline = True

    def __init__(self, item):
        self.item = item

    def __hash__(self):
        return hash((self.__class__, self.item))

    def first_chars(self, pctx):
        return self.item

    def __call__(self, stream, i, context):
        if i < len(stream) and stream.startswith(self.item, i):
            return self.item, i + 1
        else:
            return Miss, None

    def build(self, bld):
        bld.line("if i >= len(stream) or not stream.startswith(%r, i):" %
                 self.item)
        bld.line("    out = Miss")
        bld.line("else:")
        bld.line("    out = %r" % self.item)
        bld.line("    i += 1")


class String(Rule):
    """
    Matches a given string.
    """

    inline = True

    def __init__(self, s):
        self.s = s

    def __hash__(self):
        return hash((self.__class__, self.s))

    def _repr(self):
        return repr(self.s)

    def fixed_length(self, pctx=None):
        return len(self.s)

    def first_chars(self, pctx):
        return self.s[0]

    def __call__(self, stream, i, context):
        s = self.s
        if stream.startswith(s, i):
            return s, i + len(s)
        else:
            return Miss, None

    def build(self, bld):
        bld.line("if stream.startswith(%r, i):" % self.s)
        bld.line("    out = %r" % self.s)
        bld.line("    i += %d" % len(self.s))
        bld.line("else:")
        bld.line("    out = Miss")


class Among(Rule):
    """
    Matches any of a set of characters.
    """

    _fixedlen = 1
    inline = True

    def __init__(self, items):
        self.items = items

    def __hash__(self):
        return hash((self.__class__, self.items))

    def _repr(self):
        return repr(self.items)

    def first_chars(self, pctx):
        return "".join(it[0] for it in self.items)

    def __call__(self, stream, i, context):
        if i < len(stream):
            x = stream[i]
            if x in self.items:
                return x, i + 1
        return Miss, None

    def build(self, bld):
        setstring = charset_string(self.items)
        charset = bld.add_constant("_charset", setstring)
        bld.line("if i < len(stream) and stream[i] in %s:" % charset)
        bld.line("    out = stream[i]")
        bld.line("    i += 1")
        bld.line("else:")
        bld.line("    out = Miss")


class Regex(Rule):
    """
    Matches a regular expression. The output is the whole match, and any named
    groups are added to the context as variables.
    """

    inline = True
    _fixedlen = None

    def __init__(self, pattern, groups=True):
        self.pattern = pattern
        self.expr = re.compile(pattern, re.UNICODE)
        self.groups = groups

    def __hash__(self):
        return hash((self.__class__, self.pattern))

    def _repr(self):
        return repr(self.pattern)

    def __call__(self, stream, i, context):
        m = self.expr.match(stream, i)
        if m:
            if self.groups:
                context.update(m.groupdict())
            return m.group(0), m.end()
        return Miss, None

    def build(self, bld):
        name = bld.add_regex(self.pattern, self.expr)
        match = bld.generate_id("match")
        bld.line("%s = %s.match(stream, i)" % (match, name))
        bld.line("if %s:" % match)
        bld.line("    out = %s.group(0)" % match)
        bld.line("    i = %s.end()" % match)
        if self.groups:
            bld.line("    context.update(%s.groupdict())" % match)
        bld.line("else:")
        bld.line("    out = Miss")


class Value(Rule):
    """
    Always matches, outputs a given value.
    """

    _fixedlen = 0
    inline = True

    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return hash((self.__class__, self.value))

    def __call__(self, stream, i, context):
        return self.value, i

    def build(self, bld):
        bld.line("out = %r" % (self.value,))


class MultiRule(Rule):
    """
    Base class for rules that encapsulate multiple sub-rules (Or and Seq).
    """

    def __init__(self, rules):
        self.rules = rules

    def __hash__(self):
        return hash((self.__class__, tuple(self.rules)))

    def children(self):
        return self.rules

    def has_binding(self, bld):
        return any(r.has_binding(bld) for r in self.rules)

    def snap(self, pctx, seen):
        if self not in seen:
            seen.add(self)
            self.rules = [r.snap(pctx, seen) for r in self.rules]
        return self


class Or(MultiRule):
    """
    Checks multiple sub-rules in sequence, returns the output of the first one
    that matches, or Miss if none of the sub-rules match.
    """

    def __init__(self, *rules):
        self.rules = [ensure(r) for r in rules]
        self._fmap = None

    def fixed_length(self, pctx=None):
        if any(r.fixed_length() is None for r in self.rules):
            return None

        length = self.rules[0].fixed_length(pctx)
        for r in self.rules[1:]:
            if r.fixed_length() != length:
                return None
        return length

    def is_optional(self):
        return all(r.is_optional() for r in self.rules)

    def first_chars(self, pctx):
        s = set()
        for rule in self.rules:
            firsts = rule.first_chars(pctx)
            if firsts is None:
                return None
            s.update(firsts)
        return "".join(s)

    def __call__(self, stream, i, context):
        rules = self.rules
        fmap = self._fmap
        if fmap is None:
            fmap = self._fmap = make_firstmap(rules, context)

        if i < len(stream):
            rules = fmap.get(stream[i], fmap[None])
        if not rules:
            return Miss, None

        for rule in rules:
            c = context.push()
            out, newi = rule.accept(stream, i, c)
            if out is Miss:
                pass
            else:
                context.update(c.first())
                return out, newi

        return Miss, None

    def build(self, bld):
        fmap = make_firstmap(self.rules, bld.context)

        fm_name = bld.add_constant("%s_fm" % self.rulename() or "or",
                                   firstmap_string(bld, fmap))
        bld.line("targets = %s[None]" % fm_name)
        bld.line("if i < len(stream):")
        bld.line("    targets = %s.get(stream[i], targets)" % fm_name)
        bld.line("if targets:")
        bld.line("    for rule in targets:")
        bld.line("        out, new = rule(stream, i, context)")
        bld.line("        if out is not Miss:")
        bld.line("            i = new")
        bld.line("            break")
        bld.line("    else:")
        bld.line("        out = Miss")
        bld.line("else:")
        bld.line("    out = Miss")


class Seq(MultiRule):
    """
    Checks that a sequence of sub-rules match one after the other. This rule
    only matches if all sub-rules match in sequence.
    """

    def __init__(self, *rules):
        self.rules = [ensure(r) for r in rules]

    def fixed_length(self, pctx=None):
        length = 0
        for r in self.rules:
            rlen = r.fixed_length(pctx)
            if rlen is None:
                return None
            length += rlen
        return length

    def is_optional(self):
        return all(r.is_optional() for r in self.rules)

    def first_chars(self, pctx):
        if self.rules and isinstance(self.rules[0], FirstChars):
            return self.rules[0].first_chars(pctx)

        firsts = set()
        for rule in self.rules:
            if isinstance(rule, Call):
                rule = rule.resolve(pctx)

            if isinstance(rule, (Wall, LookBehind, LineStart)):
                continue

            fs = rule.first_chars(pctx)
            if fs is None and rule.fixed_length() == 0:
                continue

            if rule.is_optional():
                optfs = rule.first_chars(pctx)
                if optfs:
                    firsts.update(optfs)
                    continue

            if fs:
                firsts.update(fs)
                return firsts
            else:
                return None

    def __call__(self, stream, i, context):
        c = context.push()
        out = None
        wall = None
        for r in self.rules:
            if isinstance(r, Wall):
                wall = r
                continue

            out, newi = r.accept(stream, i, c)
            if out is Miss:
                if wall:
                    raise Exception("%r did not match at %s" %
                                    (wall, row_and_col(stream, i)))
                return Miss, None
            i = newi
        return out, i

    def build(self, bld):
        has_bind = self.has_binding(bld)

        savectx = bld.generate_id("savectx")
        active = bld.generate_id("active")
        savei = bld.generate_id("savei")

        bld.line("%s = i" % savei)
        if has_bind:
            bld.line("%s = context" % savectx)
            bld.line("context = context.push()")
        bld.line("%s = True" % active)

        for rule in self.rules:
            if isinstance(rule, (Wall, FirstChars)):
                continue

            firsts = rule.first_chars(bld.context)
            if firsts:
                bld.line("if %s and i < len(stream) and stream[i] not in %r:" %
                         (active, "".join(firsts)))
                bld.line("    %s = False" % active)
                bld.line("    out = Miss")

            bld.line("if %s:" % active)
            bld.call(rule, indent=4)
            bld.line("    %s = out is not Miss" % active)

        if has_bind:
            bld.line("context = %s" % savectx)
        bld.line("if not %s:" % active)
        bld.line("    i = %s" % savei)


class Not(Rule):
    """
    Matches if a sub-rule *doesn't* match.
    """

    _fixedlen = 0

    def __init__(self, rule):
        self.rule = ensure(rule)

    def __hash__(self):
        return hash((self.__class__, self.rule))

    def children(self):
        return (self.rule, )

    def __call__(self, stream, i, context):
        out, _ = self.rule.accept(stream, i, context)
        if out is Miss:
            return Empty, i
        else:
            return Miss, None

    def first_chars(self, pctx):
        return None

    def build(self, bld):
        bld.call(self.rule)
        bld.line("if out is Miss:")
        bld.line("    out = Empty")
        bld.line("else:")
        bld.line("    out = Miss")


class Repeat(Rule):
    """
    Matches if a sub-rules matches within a certain range of repititions.
    """

    def __init__(self, rule, mintimes=0, maxtimes=None):
        self.rule = rule
        self.mintimes = mintimes
        self.maxtimes = maxtimes

    def __hash__(self):
        return hash((self.__class__, self.rule, self.mintimes, self.maxtimes))

    def children(self):
        return (self.rule, )

    def first_chars(self, pctx):
        if self.mintimes < 1:
            return None
        else:
            return self.rule.first_chars(pctx)

    def is_optional(self):
        return self.mintimes == 0

    def __call__(self, stream, i, context):
        rule = self.rule
        mintimes = self.mintimes
        maxtimes = self.maxtimes

        times = 0
        output = []
        slen = len(stream)

        while i <= slen:
            out, newi = rule.accept(stream, i, context)
            if out is Miss:
                break

            if newi <= i:
                if i == slen:
                    break
                raise Exception
            i = newi

            if out is not Empty:
                output.append(out)
            times += 1
            if maxtimes and times == maxtimes:
                break

        if times >= mintimes:
            return output, i
        else:
            return Miss, None

    def build(self, bld):
        rule = self.rule
        mintimes = self.mintimes
        maxtimes = self.maxtimes

        times = bld.generate_id("times")
        output = bld.generate_id("output")
        previ = bld.generate_id("previ")
        savei = bld.generate_id("savei")
        bld.line("%s = i" % savei)
        bld.line("%s = 0" % times)
        bld.line("%s = []" % output)
        bld.line("while i <= len(stream):")
        bld.line("    %s = i" % previ)
        bld.call(rule, indent=4)
        bld.line("    if out is Miss:")
        bld.line("        break")
        bld.line("    if i <= %s:" % previ)
        bld.line("        if stream.startswith('\\x03', i) or i == len(stream):")
        bld.line("            break")
        bld.line("        raise Exception")
        bld.line("    if out is not Empty:")
        bld.line("        %s.append(out)" % output)
        bld.line("    %s += 1" % times)
        if maxtimes is not None:
            bld.line("    if %s == %s: break" % (times, maxtimes))
        bld.line("if %s >= %s:" % (times, mintimes))
        bld.line("    out = %s" % output)
        bld.line("else:")
        bld.line("    out = Miss")
        bld.line("    i = %s" % savei)


class Star(Repeat):
    """
    Matches the sub-rule matches zero or more times.
    """

    def __init__(self, rule):
        super(Star, self).__init__(rule, mintimes=0, maxtimes=None)


class Plus(Repeat):
    """
    Matches the sub-rule matches one or more times.
    """

    def __init__(self, rule):
        super(Plus, self).__init__(rule, mintimes=1, maxtimes=None)


class Opt(Rule):
    """
    Matches the sub-rule zero or one times.
    """

    _might_be_zero = True

    def __init__(self, rule):
        self.rule = rule

    def __hash__(self):
        return hash((self.__class__, self.rule))

    def children(self):
        return (self.rule, )

    def is_optional(self):
        return True

    def __call__(self, stream, i, context):
        out, newi = self.rule.accept(stream, i, context)
        if out is Miss:
            return [], i
        else:
            return [out], newi

    def build(self, bld):
        bld.call(self.rule)
        bld.line("if out is Miss:")
        bld.line("    out = []")
        bld.line("else:")
        bld.line("    out = [out]")


class Peek(Rule):
    """
    Matches if the sub-rule would match at the given position, but does not move
    the the position forward.
    """

    _might_be_zero = True

    def __init__(self, rule):
        self.rule = ensure(rule)

    def __hash__(self):
        return hash((self.__class__, self.rule))

    def first_chars(self, pctx):
        return self.rule.first_chars(pctx)

    def children(self):
        return (self.rule, )

    def __call__(self, stream, i, context):
        out, _ = self.rule.accept(stream, i, context)
        if out is Miss:
            return Miss, None
        else:
            return Empty, i

    def build(self, bld):
        savei = bld.generate_id("savei")
        bld.line("%s = i" % savei)
        bld.call(self.rule)
        bld.line("if out is not Miss:")
        bld.line("    out = Empty")
        bld.line("i = %s" % savei)


class LookBehind(Rule):
    """
    Matches if the sub-rule matches leading up to the given position.
    """

    def __init__(self, rule):
        self.rule = ensure(rule)

    def __hash__(self):
        return hash((self.__class__, self.rule))

    def children(self):
        return (self.rule,)

    def __call__(self, stream, i, context):
        rule = self.rule
        length = rule.fixed_length()
        assert length is not None and length > 0, (rule, length)
        start = i - length
        if start >= 0:
            out, newi = rule.accept(stream, start, context)
            if out is not Miss and newi == i:
                return Empty, i
        return Miss, None

    def build(self, bld):
        length = self.rule.fixed_length(bld.context)
        if length is None:
            raise Exception("%r: %r has fixed length %r" %
                            (self, self.rule, length))

        savei = bld.generate_id("savei")
        bld.line("%s = i" % savei)
        bld.line("i -= %d" % length)
        bld.call(self.rule)
        bld.line("if out is not Miss and i == %s:" % savei)
        bld.line("    out = Empty")
        bld.line("else:")
        bld.line("    out = Miss")
        bld.line("    i = %s" % savei)


class FailIf(Rule):
    """
    If the sub-rule matches, returns a Failure value, indicating to the parent
    Mixed rule that it does not match.
    """

    _fixedlen = 0

    def __init__(self, rule):
        self.rule = rule

    def __hash__(self):
        return hash((self.__class__, self.rule))

    def children(self):
        return (self.rule, )

    def __call__(self, stream, i, context):
        out, i = self.rule.accept(stream, i, context)
        if out is Miss:
            return out, None
        else:
            return Failure, i

    def build(self, bld):
        savei = bld.generate_id("savei")
        bld.line("%s = i" % savei)
        bld.call(self.rule)
        bld.line("if out is not Miss:")
        bld.line("    out = Failure")
        bld.line("i = %s" % savei)


class FirstChars(Rule):
    """
    A "utility" rule that lets you explicitly set the "first chars" at the start
    of a sequence, for cases where the system isn't smart enough to figure them
    out itself.
    """

    _fixedlen = 0

    def __init__(self, chars):
        self.chars = chars

    def first_chars(self, pctx):
        return self.chars

    @staticmethod
    def __call__(stream, i, context):
        return Empty, i

    def build(self, bld):
        return


class Wrapper(Rule):
    """
    Base class for rules that "wrap" a sub-rule, modifying their behavior or
    output somehow.
    """

    def __init__(self, rule):
        assert isinstance(rule, Rule)
        self.rule = ensure(rule)

    # def __hash__(self):
    #     return hash((self.__class__, self.rule))

    def children(self):
        return (self.rule, )

    def fixed_length(self, pctx=None):
        return self.rule.fixed_length(pctx)

    def is_optional(self):
        return self.rule.is_optional()

    def first_chars(self, pctx):
        return self.rule.first_chars(pctx)

    def __call__(self, stream, i, context):
        return self.rule(stream, i, context)

    def has_binding(self, bld):
        return self.rule.has_binding(bld)

    def snap(self, pctx, seen):
        if self not in seen:
            seen.add(self)
            self.rule = self.rule.snap(pctx, seen)
        return self

    def build(self, bld):
        raise NotImplementedError(type(self))


class Replace(Wrapper):
    """
    If the sub-rule matches, outputs a given value instead of the sub-rule's
    output.
    """

    def __init__(self, rule, output):
        self.rule = ensure(rule)
        self.output = output

    def _repr(self):
        return self.output

    def __call__(self, stream, i, context):
        out, i = self.rule.accept(stream, i, context)
        if out is not Miss:
            out = self.output
        return out, i

    def build(self, bld):
        bld.call(self.rule)
        bld.line("if out is not Miss:")
        bld.line("    out = %r" % self.output)


class Take(Wrapper):
    """
    If the sub-rule matches, output the text corresponding to the start and end
    of the match, instead of the sub-rule's output.
    """

    def __call__(self, stream, i, context):
        out, newi = self.rule.accept(stream, i, context)
        if out is Miss:
            return Miss, None
        else:
            return stream[i:newi], newi

    def build(self, bld):
        savei = bld.generate_id("savei")
        bld.line("%s = i" % savei)
        bld.call(self.rule)
        bld.line("if out is not Miss:")
        bld.line("    out = stream[%s:i]" % savei)


class Bind(Wrapper):
    """
    If the sub-rule matches, set a variable in the context to the output value.
    """

    def __init__(self, name, rule):
        self.name = name
        self.rule = ensure(rule)

    def _repr(self):
        return repr(self.name)

    def __call__(self, stream, i, context):
        out, i = self.rule.accept(stream, i, context)
        if out is not Miss:
            context[self.name] = out
        return out, i

    def has_binding(self, bld):
        return True

    def build(self, bld):
        bld.call(self.rule)
        bld.line("if out is not Miss:")
        bld.line("    context[%r] = out" % (self.name,))


class Extent(Wrapper):
    """
    If the sub-rule matches, annotate the output span/block with an "extent"
    key indicating the start and end character indices.
    """

    def __call__(self, stream, i, context):
        start = i
        out, i = self.rule(stream, i, context)
        if out is not Miss:
            assert isinstance(out, dict)
            out["extent"] = (start, i)
        return out, i

    def build(self, bld):
        starti = bld.generate_id("starti")
        bld.line("%s = i" % starti)
        bld.call(self.rule)
        bld.line("if out is not Miss:")
        bld.line("    assert isinstance(out, dict)")
        bld.line("    out['extent'] = (%s, i)" % starti)


class Call(Rule):
    """
    Invokes another rule by name. This is how we implement circular/recursive
    definitions in the grammar.
    """

    def __init__(self, name, argexprs=()):
        self.name = name
        self.argexprs = argexprs
        self.args = [compile_expr(argexpr) for argexpr in argexprs]
        self.rule = None

    # def __hash__(self):
    #     return hash((self.__class__, self.name, tuple(self.argexprs)))

    def _repr(self):
        return "%s(%s)" % (self.name, " ".join(self.argexprs))

    def dump(self, pctx, level=0):
        print("  " * level, "Call", self.name)

    def resolve(self, pctx):
        if self.rule is not None:
            return self.rule
        else:
            return pctx.namespace[self.name]

    def first_chars(self, pctx):
        if pctx is None:
            return None
        return self.resolve(pctx).first_chars(pctx)

    def fixed_length(self, pctx=None):
        if self.rule is not None:
            return self.rule.fixed_length(None)
        elif pctx is None:
            return None
        else:
            return self.resolve(pctx).fixed_length(None)

    def __call__(self, stream, i, context):
        rule = self.resolve(context)
        if isinstance(rule, Params) and self.argexprs:
            values = dict((argname, eval(argcode, {}, context))
                          for argname, argcode in zip(rule.argnames, self.args))
            context = context.push(values)
        return rule.accept(stream, i, context)

    def has_binding(self, bld):
        rule = self.resolve(bld.context)
        return rule.has_binding(bld)

    def snap(self, pctx, seen):
        if self not in seen:
            seen.add(self)
            self.rule = self.resolve(pctx).snap(pctx, seen)
        if self.args:
            return self
        else:
            return self.rule

    def build(self, bld):
        rule = self.resolve(bld.context)
        ctx = "context"

        hasparams = isinstance(rule, Params)
        if hasparams and self.argexprs:
            args = [(argname, argexpr)
                    for argname, argexpr
                    in zip(rule.argnames, self.argexprs)
                    if argname != argexpr]
            if args:
                ctx = bld.generate_id("ctx")
                bld.line("%s = context.push()" % ctx)
                bld.line("context = context.push()")
                for argname, argexpr in args:
                    bld.line("%s[%r] = eval(%r, {}, context)" %
                             (ctx, argname, argexpr))

        bld.call_by_name(self.name, context_name=ctx)


class Call2(Call):
    """
    Invokes another rule in another module by name.
    """

    inline = True

    def __init__(self, modname, name, argexprs=()):
        self.modname = modname
        self.name = name
        self.argexprs = argexprs
        self.args = [compile_expr(argexpr) for argexpr in argexprs]

    def _repr(self):
        return "%s.%s(%s)" % (self.modname, self.name, " ".join(self.argexprs))

    def dump(self, pctx, level=0):
        print("  " * level, repr(self))

    # def __hash__(self):
    #     return hash((self.__class__, self.modname, self.name,
    #                  tuple(self.argexprs)))

    def fixed_length(self, pctx=None):
        if pctx is None:
            return None
        return self.resolve(pctx).fixed_length(None)

    def resolve(self, pctx):
        mod = pctx.namespace[self.modname]
        return getattr(mod, self.name)

    def build(self, bld):
        bld.line("out, i = %s.%s(stream, i, context)" %
                 (self.modname, self.name))


class Mixed(Rule):
    """
    Takes text until a certain rule (the "until" rule) matches. This rule does
    not consume the "until" match (it acts like a Peek). Before the until rule,
    you can optionally specify a "content" rule. The output of any matches of
    this rule are interspersed with the text.

    This allows parsing wiki text where inline markup such as links and styling
    are interspersed with text. As with BlockBreak, you could specify this
    behavior using lower-level rules, but it would be tedious and less
    efficient.
    """

    def __init__(self, until, rule=None):
        self.until = ensure(until)
        self.rule = ensure(rule) if rule else None

        until = self.until
        self.u_firsts = until.first_chars(None)

        self.rule = rule
        if rule:
            self.r_firsts = rule.first_chars(None)
        else:
            self.r_firsts = None

    # def __hash__(self):
    #     return hash((self.__class__, self.until, self.rule))

    def children(self):
        cs = [self.until]
        if self.rule:
            cs.append(self.rule)
        return cs

    def __call__(self, stream, i, context):
        until = self.until
        u_firsts = self.u_firsts
        rule = self.rule
        r_firsts = self.r_firsts

        length = len(stream)
        context = context.push()
        output = []
        lasti = i
        while i < length:
            if not u_firsts or stream[i] in u_firsts:
                out, _ = until(stream, i, context)
                if out is Miss:
                    pass
                else:
                    if out is Failure:
                        return Miss, None
                    break

            if rule and (not r_firsts or stream[i] in r_firsts):
                out, newi = rule(stream, i, context)
                if out is Miss:
                    i += 1
                elif out is Failure:
                    return Miss, None
                elif newi <= i:
                    raise Exception
                else:
                    if i > lasti:
                        output.append(stream[lasti:i])
                    output.append(out)
                    lasti = i = newi
            else:
                i += 1

        if i > lasti:
            output.append(stream[lasti:i])
        return output, i

    def snap(self, pctx, seen):
        if self not in seen:
            seen.add(self)
            self.until = self.until.snap(pctx, seen)
            if self.rule:
                self.rule = self.rule.snap(pctx, seen)
        return self

    def build(self, bld):
        savei = bld.generate_id("savei")

        until = self.until
        u_firsts = until.first_chars(bld.context)
        u_firsts = "".join(u_firsts) if u_firsts is not None else None

        rule = self.rule
        if rule:
            r_firsts = rule.first_chars(bld.context)
            r_firsts = "".join(r_firsts) if r_firsts is not None else None
        else:
            r_firsts = None

        output = bld.generate_id("output")
        bld.line("%s = []" % output)
        bld.line("lasti = i")
        bld.line("while i < len(stream):")

        if u_firsts:
            bld.line("    if i == len(stream) or stream[i] in %r:" % u_firsts)
            indent = 8
        else:
            indent = 4
        with bld.indented(indent):
            bld.line("%s = i" % savei)
            bld.call(until)
            bld.line("i = %s" % savei)
            bld.line("if out is Failure:")
            bld.line("    out = Miss")
            bld.line("    break")
            bld.line("elif out is not Miss:")
            bld.line("    break")

        if rule:
            if r_firsts:
                bld.line("    if i == len(stream) or stream[i] in %r:" % r_firsts)
                indent = 8
            else:
                indent = 4
            with bld.indented(indent):
                bld.line("%s = i" % savei)
                bld.call(rule)
                bld.line("if out is Miss:")
                bld.line("    i = %s + 1" % savei)
                bld.line("elif out is Failure:")
                bld.line("    out = Miss")
                bld.line("    break")
                bld.line("elif i <= %s:" % savei)
                bld.line("    raise Exception")
                bld.line("else:")
                bld.line("    if %s > lasti:" % savei)
                bld.line("        %s.append(stream[lasti:%s])" % (output, savei))
                bld.line("    %s.append(out)" % output)
                bld.line("    lasti = i")
            if r_firsts:
                bld.line("    else:")
                bld.line("        i += 1")
        else:
            bld.line("    i += 1")

        bld.line("if i > lasti:")
        bld.line("    %s.append(stream[lasti:i])" % output)
        bld.line("out = %s" % output)


class ApplicationArgs(Rule):
    """
    Matches a bracketed list of space-separated arguments. This is just a Rule
    object wrapper for the take_app_args function.
    """

    inline = True

    def __call__(self, stream, i, context):
        return take_app_args(stream, i)

    def build(self, bld):
        bld.line("out, i = rules.take_app_args(stream, i)")


appargs = ApplicationArgs()


class Params(Wrapper):
    """
    This rule indicates that its sub-rule should be run in a context where
    certain parameters are filled in. This rule doesn't actually do anything;
    the Call rule checks whether its target is a Params rule and fills in the
    necessary parameters if it is.
    """

    def __init__(self, rule, argnames):
        self.rule = rule
        self.argnames = argnames

    # def __hash__(self):
    #     return hash((self.__class__, self.rule, tuple(self.argnames)))

    def build(self, bld):
        bld.call(self.rule)


class Do(Rule):
    """
    Runs a compiled Python expression (using the context as the environment) and
    outputs the result.
    """

    _fixedlen = 0

    def __init__(self, source):
        self.source = source
        self.literal = self._literal(source)
        if self.literal is None:
            self.code = compile_expr(source)

    # def __hash__(self):
    #     return hash((self.__class__, self.source))

    def _literal(self, source):
        import ast
        try:
            lit = ast.literal_eval(source)
        except (SyntaxError, ValueError) as e:
            return None
        return lit

    def _repr(self):
        return self.source

    def __call__(self, stream, i, context):
        if self.literal is not None:
            result = self.literal
        else:
            result = eval(self.code, context.namespace, context)
        return result, i

    def build(self, bld):
        if self.literal is not None:
            bld.line("out = %s" % self.source)
        else:
            name = bld.add_constant("_do", "rules.compile_expr(%r)" %
                                    self.source)
            bld.line("out = eval(%s, globals(), context)" % name)


class DoCode(Rule):
    _fixedlen = 0
    inline = True

    def __init__(self, source):
        self.source = source

    def _repr(self):
        return self.source

    def __call__(self, stream, i, context):
        env = {
            "stream": stream,
            "i": i,
            "context": context,
        }
        out = eval(self.source, context.namespace, env)
        return out, i

    def build(self, bld):
        bld.line("out = %s" % self.source)


class If(Do):
    """
    Runs a compiled Python expression (using the context as the environment) and
    matches if the expression returns a truthy value, or misses otherwise.
    """

    def __call__(self, stream, i, context):
        out = eval(self.code, context.namespace, context)
        out = Empty if out else Miss
        return out, i

    def build(self, bld):
        name = bld.add_constant("_if", "rules.compile_expr(%r)" % self.source)
        bld.line("out = Empty if eval(%s, context.namespace, context) else Miss" % name)


class IfCode(DoCode):
    _fixedlen = 0
    inline = True

    def __init__(self, source):
        self.source = source

    def __call__(self, stream, i, context):
        env = {
            "stream": stream,
            "i": i,
            "context": context,
        }
        out = eval(self.source, context.namespace, env)
        out = Empty if out else Miss
        return out, i

    def build(self, bld):
        bld.line("out = Empty if (%s) else Miss" % self.source)


class Run(Rule):
    """
    Runs a function (using the context to fill in arguments by name) and outputs
    the result.
    """

    _fixedlen = 0

    def __init__(self, fn):
        self.fn = fn
        self.params, _, _, self.defaults = inspect.getfullargspec(fn)

    # def __hash__(self):
    #     return hash((self.__class__, self.fn))

    def __call__(self, stream, i, context):
        args = [(context if n == "context" else context[n])
                for n in self.params]
        return self.fn(*args), i

    def build(self, bld):
        raise Exception


class Cond(Run):
    """
    Runs a function (using the context to fill in arguments by name) and matches
    if the function returns a truthy value, or misses otherwise.
    """

    def __call__(self, stream, i, context):
        args = [(context if n == "context" else context[n])
                for n in self.params]
        if self.fn(*args):
            return Empty, i
        else:
            return Miss, None

    def build(self, bld):
        raise Exception


class PythonExpr(Rule):
    """
    Matches a Python expression, up to one of the characters in the "ends" set.
    This is a Rule object wrapper for the take_python_expr() function.
    """

    def __init__(self, ends):
        self.ends = ends

    # def __hash__(self):
    #     return hash((self.__class__, self.ends))

    def __call__(self, stream, i, context):
        return take_python_expr(stream, i, self.ends)

    def build(self, bld):
        bld.line("out, i = rules.take_python_expr(stream, i, %r)" % self.ends)


# An instance of PythonExpr for use in parsing "-> expr" syntax
value_expr = PythonExpr("\r\n)]")
# An instance of PythonExpr for use in parsing "!(expr)" and "?(expr)" syntax
action_expr = PythonExpr(")")


class Wall(Rule):
    """
    This rule doesn't do anything, but it serves as a marker in a sequence that
    past this point, the rest of the sequence must match, otherwise there's
    an error in the input file (the parent Seq rule will raise an exception).
    """

    _fixedlen = 0

    def __init__(self, name):
        self.name = name

    # def __hash__(self):
    #     return hash((self.__class__, self.name))

    def __repr__(self):
        return "[%r]" % self.name

    def __call__(self, stream, i, context):
        return Empty, i

    def build(self, bld):
        bld.line("# %s" % self.name)















