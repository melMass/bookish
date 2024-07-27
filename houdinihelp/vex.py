from __future__ import print_function
import json
import re
from collections import defaultdict
from subprocess import check_output


"""
This module contains a parser for VEX signatures. VEX signatures can be listed
in two forms: the form output by `vcc -X`, which doesn't include argument names
and puts the array indicator [] with the type in arguments; and the form used in
function declarations and the documentation, which puts the array indicator
after the name, because nothing is ever allowed to make sense in Houdini.

The main purpose of parsing the two different signature forms is to compare
them: once you parse a signature from the docs into a "template" (the docs allow
a few type wildcards that are not in actual VEX to make the docs more compact),
and a signature from `vcc -X` into a "target", you can see if the template
describes the target with `template.matches(target)`. This lets you check if all
signatures known to `vcc` are documented.
"""

ARGLIST_OPEN_BRACKET = "("
ARGLIST_CLOSE_BRACKET = ")"
ARGLIST_SEPARATOR = ", "


# List of known types. This includes some structs because there's currently no
# way to pragmatically get a list of global structs
VEXTYPES = ("int float vector vector2 vector4 matrix2 matrix3 matrix4 matrix "
            "string bsdf dict light material void lpeaccumulator").split()
TYPESET = frozenset(VEXTYPES)

SHADING_CONTEXTS = "surface displace light shadow fog".split()
SHADING_CONTEXT_SET = set(SHADING_CONTEXTS)

# These statements don't need big function-style docs
IGNORE_STATEMENTS = frozenset(("do", "for", "while", "if"))


# Exceptions

class NoMatch(Exception):
    """
    Raised by a VexPart when what it's trying to parse doesn't match the given
    string. This is usually caught by a caller so the caller can try a different
    pattern, but it may bubble all the way up if the given string is not a valid
    VEX signature.
    """

    def __init__(self, cls, string, pos, expected):
        self.cls = cls
        self.string = string
        self.pos = pos
        self.message = "Error in %r at %d: %s expected %s" % (
            string, pos, cls.__name__, expected
        )

    def __str__(self):
        return self.message


# Wiki API

def parse_vex(vexstring):
    """
    Parses the given signature string into a VexPart object.
    """

    return Signature.parse(vexstring)


def vex_to_wiki(vexstring):
    """
    Parses the given signature string and returns a wiki json representation.
    """

    try:
        sig = Signature.parse(vexstring)
        return sig.wiki()
    except NoMatch as e:
        return {
            "type": "vexerror",
            "text": [vexstring],
            "error": str(e),
        }


# Parsing context

class Context(object):
    """
    Used the pass configuration down to the various parsing parts.

    :param doc_mode: True if we are parsing a documentation template, False if
        we are parsing a signature from `vcc -X`.
    """

    def __init__(self, doc_mode=True, level=0):
        self.doc_mode = doc_mode
        self.level = level


# Helper functions

def wikispan(text, typename, role="vexmarkup"):
    """
    Returns a wiki json span with the given type and role.
    """

    if not isinstance(text, list):
        text = [text]
    return {"type": typename, "role": role, "text": text}


def wikiconcat(*args):
    """
    Concatenates pieces of wiki text and returns a new wiki text list.
    """

    out = []
    for arg in args:
        if isinstance(arg, list):
            out.extend(arg)
        else:
            out.append(arg)
    return out


# Vex objects

class VexPart(object):
    """
    Base class for parsing bits of a VEX signature. The parsing methods are
    class methods that return a tree of instances representing the parsed
    signature.
    """

    ws_exp = re.compile("[ \t]*")

    # Instance methods

    def __repr__(self):
        return "<%s>" % type(self).__name__

    def typecode(self):
        raise NotImplementedError

    def is_meta(self):
        return False

    def matches(self, other):
        """
        Returns True if this "template" signature matches the given "target"
        signature.

        Note that this is NOT the same as being equal to other. Equality testing
        is exact, whereas this method tests whether other can match this
        object's template pattern.
        """

        raise NotImplementedError

    def string(self):
        """
        Returns a plain string representation of the part.
        """

        raise NotImplementedError

    def wiki(self):
        """
        Returns a wiki text representation of the part.
        """

        raise NotImplementedError

    # Parsing class methods

    @classmethod
    def parse(cls, string, pos=0, **kwargs):
        """
        Parses the given string and returns a VexPart tree or raises NoMatch.
        Any keyword arguments are passed to the `Context()` constructor.
        """

        context = Context(**kwargs)
        obj, _ = cls.take(context, string, pos)
        return obj

    @classmethod
    def take(cls, ctx, string, pos):
        # Mid-level method that calls the actual implementation in _take(). This
        # exists as a central place to wrap checking and debug code around every
        # call to _take().
        assert pos < len(string)
        return cls._take(ctx, string, pos)

    @classmethod
    def _take(cls, ctx, string, pos):
        # Parsing implementation. If this part matches string at pos, return a
        # tuple of (part_instance, newpos), otherwise raise NoMatch.
        raise NotImplementedError

    @classmethod
    def expected(cls):
        # Should return a string representing what this part expects to see when
        # it's called to parse, for error reporting
        return cls.__name__

    @classmethod
    def expect(cls, string, pos, text):
        # Helper method that takes a literal string from the parse string,
        # returns the new position after the literal, or raises NoMatch
        if string.startswith(text, pos):
            return pos + len(text)
        else:
            raise NoMatch(cls, string, pos, text)

    @classmethod
    def expect_regex(cls, string, pos, expr):
        # Helper method that takes a regex, returns the new position after the
        # match, or raises NoMatch
        m = expr.match(string, pos)
        if m:
            return m.end()
        else:
            raise NoMatch(cls, string, pos, expr.pattern)

    @classmethod
    def choice(cls, ctx, string, pos, choices):
        # Helper method that takes the first of a list of classes that matches
        for c in choices:
            try:
                return c.take(ctx, string, pos)
            except NoMatch:
                pass

        ex = ",".join(c.expected() for c in choices)
        raise NoMatch(cls, string, pos, "one of %s" % ex)

    @classmethod
    def optional_text(cls, string, pos, optstring):
        # Helper method that takes a literal string if it matches, otherwise
        # doesn't move forward. Returns a tuple of (found_bool, newpos).
        try:
            pos = cls.expect(string, pos, optstring)
            return True, pos
        except NoMatch:
            return False, pos

    @classmethod
    def optional(cls, ctx, string, pos, optcls):
        # Helper method that tries a class and returns its output if it
        # matched, or (None, pos) if it didn't
        try:
            return optcls.take(ctx, string, pos)
        except NoMatch:
            return None, pos

    @classmethod
    def ws(cls, string, pos, required=False):
        # Helper method that parses optional whitespace. If required=True, the
        # string must have whitespace at the given position.
        found = False
        while pos < len(string) and string[pos].isspace():
            found = True
            pos += 1
        if required and not found:
            raise NoMatch(cls, string, pos, "whitespace")
        return pos

    @classmethod
    def take_type(cls, ctx, string, pos, allow_array=True, allow_choice=True):
        # Helper method that tries to match a type pattern. allow_array is
        # True if [] goes with the type in this position, or False if [] goes
        # after the name in the part of the signature being parsed (boo!).
        classes = [AnyType, TypeAtom]
        if allow_array:
            classes = [ArrayType] + classes
        if allow_choice:
            classes = [TypeChoice] + classes
        return cls.choice(ctx, string, pos, classes)


class RegexVexPart(VexPart):
    """
    Middleware class for subclasses that parse using a regex.
    """

    exp = None

    def matches(self, other):
        raise NotImplementedError

    def string(self):
        raise NotImplementedError

    def wiki(self):
        raise NotImplementedError

    @classmethod
    def expected(cls):
        return cls.exp.pattern

    @classmethod
    def _from_match(cls, ctx, m):
        return cls(m.group(0))

    @classmethod
    def _take(cls, ctx, string, pos):
        m = cls.exp.match(string, pos)
        if m:
            return cls._from_match(ctx, m), m.end()
        raise NoMatch(cls, string, pos, cls.exp.pattern)


class Identifier(RegexVexPart):
    """
    Function name or argument name.
    """

    exp = re.compile("[A-Za-z_][A-Za-z0-9_]*")

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return "<%r>" % self.name

    def __eq__(self, other):
        return type(other) is type(self) and self.name == other.name

    def __hash__(self):
        return hash(type(self)) ^ hash(self.name)

    def matches(self, other):
        if isinstance(other, MissingIdentifier):
            return True
        if isinstance(other, Identifier):
            return self.name == other.name

    def string(self):
        return self.name

    def wiki(self):
        return wikispan(self.name, "vexname")

    @classmethod
    def expected(cls):
        return "identifier"


class MissingIdentifier(VexPart):
    """
    Represents a missing name (as in a target parsed from `vcc -X` output, which
    doesn't have argument names).
    """

    def __repr__(self):
        return "<noname>"

    def __eq__(self, other):
        return type(self) is type(other)

    def __hash__(self):
        return hash(type(self))

    def matches(self, other):
        return isinstance(other, (MissingIdentifier, Identifier))

    def string(self):
        return ""

    def wiki(self):
        return ""

    @classmethod
    def _take(cls, ctx, string, pos):
        raise Exception("This should never be called")

    @classmethod
    def expected(cls):
        raise Exception("MissingIdentifier.expected() should never be called")


class TypeAtom(RegexVexPart):
    """
    Represents an atomic type or struct.
    """

    exp = re.compile("(" + "|".join(VEXTYPES) + ")((?=[ |\t,;)\\[])|$)")

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return type(other) is type(self) and self.name == other.name

    def __hash__(self):
        return hash(type(self)) ^ hash(self.name)

    def __repr__(self):
        return "<type %r>" % self.name

    def typecode(self):
        return self.name

    def basetype(self):
        return self

    def matches(self, other):
        return isinstance(other, TypeAtom) and self.name == other.name

    def string(self):
        return self.name

    def wiki(self):
        return wikispan(self.name, "vextype")


class TypeChoice(VexPart):
    """
    Reresents a choice between two or more types, e.g. int|float. This is not
    actually part of VEX, but is used in the documentation to the docs clearer
    and more compact.
    """

    atom_pattern = "(" + "|".join(VEXTYPES) + ")"

    def __init__(self, types):
        self.types = sorted(types, key=lambda t: t.typecode())

    def __repr__(self):
        return "<typechoice %s>" % " ".join(repr(t) for t in self.types)

    def __eq__(self, other):
        return type(other) is type(self) and self.types == other.types

    def __hash__(self):
        h = hash(type(self))
        for t in self.types:
            h ^= hash(t)
        return h

    def typecode(self):
        return self.string()

    def matches(self, other):
        return any(t.matches(other) for t in self.types)

    def string(self):
        return "|".join(t.typecode() for t in self.types)

    def wiki(self):
        return wikispan(self.string(), "vexpattern")

    @classmethod
    def _take(cls, ctx, string, pos):
        # Whitespace
        pos = cls.ws(string, pos)
        taking = True
        types = []

        while taking:
            # Take type atom
            try:
                t, pos = cls.take_type(ctx, string, pos, allow_choice=False)
            except NoMatch:
                break

            types.append(t)
            if string.startswith("|", pos):
                pos += 1
            else:
                taking = False

        if not types:
            raise NoMatch(cls, string, pos, "typechoice")
        elif len(types) == 1:
            return types[0], pos
        else:
            return cls(types), pos

    @classmethod
    def expected(cls):
        return "type(|type)+"


class AnyType(RegexVexPart):
    """
    Represents a metasyntactic wilcard matching any type, e.g. <type>. This is
    not actually part of VEX, but is used in the documentation to the docs
    clearer and more compact.
    """

    exp = re.compile("<([A-Za-z_][A-Za-z0-9_]*)>(?=[ )\t,;\\[]|$)")

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return "<anytype %r>" % self.name

    def __eq__(self, other):
        return type(other) is type(self) and self.name == other.name

    def __hash__(self):
        return hash(type(self)) ^ hash(self.name)

    def is_meta(self):
        return True

    def meta_name(self):
        return self.name

    def matches(self, other):
        if not isinstance(other, TypeAtom):
            return False

        if self.name == "vector":
            return (
                isinstance(other, TypeAtom) and
                other.name in ("vector2", "vector", "vector4")
            )
        elif self.name == "matrix":
            return (
                isinstance(other, TypeAtom) and
                other.name in ("matrix2", "matrix3", "matrix4", "matrix")
            )
        elif self.name in ("geometry", "stage"):
            return (
                isinstance(other, TypeAtom) and
                other.name in ("int", "string")
            )
        else:
            return True

    def string(self):
        return "<%s>" % self.name

    def wiki(self):
        return wikispan(self.string(), "vexpattern")

    @classmethod
    def _from_match(cls, ctx, m):
        return cls(m.group(1))

    @classmethod
    def expected(cls):
        return "'any' type"


class ArrayType(VexPart):
    """
    Represents an array type. This is a wrapper around a VexPart instance
    representing the item type.
    """

    def __init__(self, subtype):
        if not isinstance(subtype, (TypeAtom, TypeChoice, AnyType)):
            raise ValueError("Can't wrap %s in ArrayType" % subtype)
        self.subtype = subtype

    def __repr__(self):
        return "<array of %s>" % self.subtype

    def __eq__(self, other):
        return type(other) is type(self) and self.subtype == other.subtype

    def __hash__(self):
        return hash(type(self)) ^ hash(self.subtype)

    def typecode(self):
        return self.subtype.typecode() + "[]"

    def is_meta(self):
        return self.subtype.is_meta()

    def meta_name(self):
        assert self.is_meta()
        return self.subtype.meta_name()

    def basetype(self):
        return self.subtype

    def matches(self, other):
        return (isinstance(other, ArrayType) and
                self.subtype.matches(other.subtype))

    def string(self):
        return "%s[]" % self.subtype.string()

    def wiki(self):
        return wikiconcat(self.subtype.wiki(), "[]")

    @classmethod
    def _take(cls, ctx, string, pos):
        t, pos = cls.choice(ctx, string, pos, [AnyType, TypeAtom])
        pos = cls.ws(string, pos)
        pos = cls.expect(string, pos, "[]")
        return cls(t), pos

    @classmethod
    def expected(cls):
        return "array type"


class VexType(VexPart):
    @classmethod
    def _take(cls, ctx, string, pos):
        t, pos = TypeAtom.take(ctx, string, pos)
        pos = cls.ws(string, pos)
        isarray, pos = cls.optional_text(string, pos, "[]")

        if isarray:
            return ArrayType(t), pos
        else:
            return t, pos


class Argument(VexPart):
    """
    Represents an argument in the function signature. This is a compound object
    containing the various parts of the argument (type, output indicator, name,
    optional).
    """

    eq_exp = re.compile("=([^,;)]+)")

    def __init__(self, t, out, ident, optional=None):
        self.type = t
        self.out = out
        self.ident = ident
        self.optional = optional

    def __repr__(self):
        return "<arg %s %s out=%s opt=%s>" % (
            self.type, self.ident, self.out, self.optional
        )

    def __eq__(self, other):
        return (type(other) is type(self) and
                self.type == other.type and
                self.out == other.out and
                self.ident == other.ident and
                self.optional == other.optional)

    def __hash__(self):
        return (hash(type(self)) ^
                hash(self.type) ^
                hash(self.out) ^
                hash(self.ident) ^
                hash(self.optional))

    def is_meta(self):
        return self.type.is_meta()

    def meta_name(self):
        assert self.is_meta()
        return self.type.meta_name()

    def typecode(self):
        return self.type.typecode()

    def basetype(self):
        return self.type.basetype()

    def matches(self, other):
        return (
            isinstance(other, Argument) and
            self.type.matches(other.type) and
            self.out == other.out and
            self.ident.matches(other.ident)
        )

    def string(self):
        return "%s %s%s%s" % (self.type.string(),
                              "&" if self.out else "",
                              self.ident.string(),
                              self.optional or "")

    def wiki(self):
        basetype = self.type
        isarray = isinstance(basetype, ArrayType)
        if isarray:
            basetype = self.type.subtype

        return {
            "type": "vexargument",
            "role": "vexmarkup",
            "vextype": basetype.wiki(),
            "vexout": self.out,
            "text": self.ident.name,
            "vexopt": self.optional,
            "isarray": isarray,
        }

    @classmethod
    def _take(cls, ctx, string, pos):
        # Parsing an argument is more difficult than it should be because VEX
        # syntax and vcc -X output are inconsistent and non-orthagonal

        # First, if the argument is "...", it represents that variadic arguments
        # are allowed. Return a special Argument subclass representing variadic
        # arguments, we're done.
        dotdotdot, pos = cls.optional_text(string, pos, "...")
        if dotdotdot:
            return VariadicArgs(), pos

        # Sometimes in the docs an argument is marked as "const". This isn't
        # included in the vcc -X output and doesn't really mean much, so we
        # parse it and throw it away
        const, pos = cls.optional_text(string, pos, "const ")

        # We have to parse the rest of the argument differently depending on
        # whether this signature is from the docs or from vcc -X, because
        # uuuuuuuuuuggggggggghhhhhh
        if ctx.doc_mode:
            # Take a type (wihtout [])
            t, pos = cls.take_type(ctx, string, pos, allow_array=False)
            # Whitespace
            pos = cls.ws(string, pos)
            # Take optional output indicator (&)
            out, pos = cls.optional_text(string, pos, "&")

            # If the type is "<geometry>", it is a special case that is not
            # followed by a name
            if isinstance(t, AnyType) and t.name in ("geometry", "stage"):
                ident = Identifier(t.name)
            else:
                # Take the argument name
                ident, pos = Identifier.take(ctx, string, pos)

            # Take optional array indicator ([])
            isarray, pos = cls.optional_text(string, pos, "[]")
            if isarray:
                t = ArrayType(t)

            # Take an optional =x part after the argument that indicates this
            # argument is optional. This is not actually part of VEX, it's used
            # in the docs for compactness.
            optional = None
            optm = cls.eq_exp.match(string, pos)
            if optm:
                optional = optm.group(0)
                pos = optm.end()

        else:
            # Take a type (with optional [])
            t, pos = cls.take_type(ctx, string, pos, allow_array=True)
            # Whitespace
            pos = cls.ws(string, pos)
            # Take optional output indicator (&)
            out, pos = cls.optional_text(string, pos, "&")
            # Take name
            ident = MissingIdentifier()
            # No defaults in vcc -X output
            optional = None

        # Whitespace after argument (ArgumentList takes care of argument
        # separators)
        pos = cls.ws(string, pos)
        # Return the instance representing this argument
        return cls(t, out, ident, optional), pos


class VariadicArgs(VexPart):
    """
    Represents variadic arguments (...) in a function signature.
    """

    def __init__(self, pairs=False):
        self.pairs = pairs
        self.optional = None

    def __eq__(self, other):
        return type(self) is type(other)

    def __hash__(self):
        return hash(type(self))

    def __repr__(self):
        return "<...%s>" % (" pairs" if self.pairs else "")

    def string(self):
        return "..."

    def wiki(self):
        return wikispan(self.string(), "vexvariadic")

    def matches(self, other):
        return isinstance(other, VariadicArgs)


class ArgumentList(VexPart):
    """
    Represents zero or more arguments in a function signature.
    """

    separator_exp = re.compile("[;,]\\s+")

    def __init__(self, args):
        self.args = args

    def __repr__(self):
        return "(%s)" % ",".join(repr(a) for a in self.args)

    def __eq__(self, other):
        return type(self) is type(other) and self.args == other.args

    def __hash__(self):
        h = hash(type(self))
        for arg in self.args:
            h ^= hash(arg)
        return h

    def check_meta_types(self, arglist, typemap):
        # Compare template and concrete arguments; if the template argument
        # is meta, check that the concrete type is the same as previous
        # uses

        for template_arg, concrete_arg in zip(self.args, arglist.args):
            if template_arg.is_meta():
                # This argument has a meta type... get the meta name and the
                # concrete type atom
                metaname = template_arg.meta_name()
                typecode = concrete_arg.basetype().typecode()

                # Have we seen this meta name before in the template?
                if metaname in typemap:
                    # Yes, make sure it's the same type as before
                    if typemap[metaname] != typecode:
                        # It's not the same, the template doesn't match
                        return False
                else:
                    # No, remember this type to check future uses of the name
                    typemap[metaname] = typecode

        # No complaints, so we match
        return True

    def matches(self, other):
        if not isinstance(other, ArgumentList):
            return False

        args = self.args
        oargs = other.args

        if len(oargs) > len(args):
            return False
        if len(args) == 0 and len(oargs) == 0:
            return True

        has_optionals = any(arg.optional for arg in args)
        if not has_optionals and len(args) != len(oargs):
            return False

        # If none of the args is optional, or we have the exact number of
        # arguments, just do a straight check
        if len(args) == len(oargs):
            return all(a.matches(o) for a, o in zip(args, oargs))

        if has_optionals:
            test = args[:]
            last = len(args)
            while last >= 1 and test[-1].optional:
                last -= 1
                if last == 0 and len(oargs) == 0:
                    return True
                if all(a.matches(o) for a, o in zip(test[:last], oargs)):
                    return True

        return False

    def string(self):
        return "%s%s%s" % (
            ARGLIST_OPEN_BRACKET,
            ARGLIST_SEPARATOR.join(arg.string() for arg in self.args),
            ARGLIST_CLOSE_BRACKET
        )

    def wiki(self):
        out = [ARGLIST_OPEN_BRACKET]
        first = True
        for arg in self.args:
            if not first:
                out.append(ARGLIST_SEPARATOR)
            first = False
            out.append(arg.wiki())
        out.append(ARGLIST_CLOSE_BRACKET)
        return out

    @staticmethod
    def _check_args(args):
        # vcc -X reports the signature of a function with no arguments as
        # foo( void ), so check for this and transform it into an empty arg list
        if len(args) == 1:
            arg = args[0]
            if not isinstance(arg, VariadicArgs):
                if isinstance(arg.type, TypeAtom) and arg.type.name == "void":
                    args = []
        return args

    @classmethod
    def _take(cls, ctx, string, pos):
        args = []

        # Take the opening paren
        pos = cls.expect(string, pos, "(")
        # Whitespace
        pos = cls.ws(string, pos)

        # If the next thing is a close paren, the function has no arguments,
        # we're done
        empty, epos = cls.optional_text(string, pos, ")")
        if empty:
            return cls([]), epos

        # Take the first argument
        firstarg, pos = Argument.take(ctx, string, pos)
        args.append(firstarg)

        # Look for zero or more sequences of argument-separator + argument
        while pos < len(string):
            # Whitespace
            pos = cls.ws(string, pos)
            # If the next thing is a close paren, we're done
            endbracket, epos = cls.optional_text(string, pos, ")")
            if endbracket:
                return cls(cls._check_args(args)), epos

            # Take argument separator
            pos = cls.expect_regex(string, pos, cls.separator_exp)
            # Take argument
            nextarg, pos = Argument.take(ctx, string, pos)
            args.append(nextarg)

        # If we get here, we never saw a close paren above, so no match
        raise NoMatch(cls, string, pos, ")")


class Signature(VexPart):
    """
    Top-level object represents the entire signature. Contains the return type,
    function name, and argument list.
    """

    def __init__(self, rtype, ident, arglist, original=None):
        self.rtype = rtype
        self.ident = ident
        self.arglist = arglist
        self.original = original

    def __repr__(self):
        return "<sig %s %s %s>" % (self.rtype, self.ident, self.arglist)

    def __eq__(self, other):
        return (type(other) is type(self) and
                self.rtype == other.rtype and
                self.ident == other.ident and
                self.arglist == other.arglist)

    def __hash__(self):
        return (hash(type(self)) ^
                hash(self.rtype) ^
                hash(self.ident) ^
                hash(self.arglist))

    def check_meta_types(self, other):
        # This dictionary will map metasynatactic names in the template to
        # concrete types in the vcc output
        typemap = {}

        # If the template's return type is meta, put it in the map
        if self.rtype.is_meta():
            typemap[self.rtype.meta_name()] = other.rtype.basetype().typecode()

        return self.arglist.check_meta_types(other.arglist, typemap)

    def matches(self, other):
        return (
            isinstance(other, Signature) and
            self.rtype.matches(other.rtype) and
            self.ident.matches(other.ident) and
            self.arglist.matches(other.arglist) and
            self.check_meta_types(other)
        )

    def string(self):
        if self.original:
            return self.original
        else:
            return "%s %s%s" % (self.rtype.string(),
                                self.ident.string(),
                                self.arglist.string())

    def wiki(self):
        return [
            wikispan(self.rtype.wiki(), "vexrtype"),
            " ",
            self.ident.wiki(),
        ] + self.arglist.wiki()

    @classmethod
    def parse_template(cls, string):
        return cls.parse(string, doc_mode=True)

    @classmethod
    def parse_concrete(cls, string):
        return cls.parse(string, doc_mode=False)

    @classmethod
    def _take(cls, ctx, string, pos):
        # Whitespace
        pos = cls.ws(string, pos)
        # Take return type
        rtype, pos = cls.take_type(ctx, string, pos)
        # Whitespace
        pos = cls.ws(string, pos, required=True)
        # Take function name
        ident, pos = Identifier.take(ctx, string, pos)
        # Take parenthesized argument list
        arglist, pos = ArgumentList.take(ctx, string, pos)

        return cls(rtype, ident, arglist, string), pos


# Testing utilities

class Reporter(object):
    def start(self, checker):
        pass

    def parser_error(self, fnname, string, exception):
        pass

    def parsed_signature(self, context, sig):
        pass

    def parsed_doc_page(self, fnname):
        pass

    def parsed_doc_sig(self, sig):
        pass

    def extra_context(self, name):
        pass

    def wrong_function_name(self, fnname, wrong_string):
        pass

    def extra_doc(self, fnname):
        pass

    def missing_doc(self, fnname, contexts):
        pass

    def missing_statement_doc(self, statementname, contexts):
        pass

    def compared_signatures(self, docsig, vccsig, matched):
        pass

    def extra_global(self, glob, context):
        pass

    def missing_global(self, glob, context):
        pass

    def extra_doc_signature(self, fnname, sig):
        pass

    def missing_doc_signature(self, fnname, vccsig, docsigs):
        pass

    def wrong_contexts(self, fnname, stated, actual):
        pass

    def marked_deprecated(self, signature):
        pass

    def finish(self, checker):
        pass


class PrintReporter(Reporter):
    def __init__(self, file=None, print_footer=True):
        import sys

        self.file = file or sys.stdout
        self.print_footer = print_footer

        self._missing_count = 0
        self._has_missing = set()

    def parser_error(self, fnname, string, exception):
        print("ERROR parsing in", fnname, file=self.file)
        print(string, file=self.file)
        print((" " * exception.pos) + "^", file=self.file)

    def extra_context(self, name):
        print("EXTRA context doc for unknown context", name, file=self.file)

    def wrong_function_name(self, fnname, wrong_string):
        print("ERROR signature for", fnname, "has wrong function name",
              file=self.file)
        print(wrong_string, file=self.file)

    def extra_doc(self, fnname):
        print("UNKNOWN function", fnname, "has documentation", file=self.file)

    def missing_doc(self, fnname, contexts):
        print("MISSING documentation for", fnname, "in contexts", contexts,
              file=self.file)

    def missing_statement_doc(self, sname, contexts):
        print("MISSING doc for statement", sname, "in contexts", contexts,
              file=self.file)

    def wrong_contexts(self, fnname, stated, actual):
        print("WRONG CONTEXTS for", fnname, "should be", actual,
              file=self.file)

    # def compared_signatures(self, docsig, vccsig, matched):
    #     print(docsig.original, vccsig.original, matched)

    def extra_global(self, glob, context):
        print("EXTRA global", glob, "in", context, file=self.file)

    def missing_global(self, glob, context):
        print("MISSING global", glob, "in", context, file=self.file)

    def extra_doc_signature(self, fnname, sig):
        print("EXTRA pattern", sig.string(), "in", fnname, file=self.file)

    def missing_doc_signature(self, fnname, vccsig, docsigs):
        print("MISSING pattern for", vccsig.string(), "in", fnname,
              file=self.file)
        self._missing_count += 1
        self._has_missing.add(fnname)

    def finish(self, checker):
        if self.print_footer:
            print("Total: ", self._missing_count, "missing signatures across",
                  len(self._has_missing), "functions", file=self.file)


class ContextRewriteReporter(Reporter):
    def __init__(self, funcdir, extension=".txt"):
        self.funcdir = funcdir
        self.ext = extension

    def wrong_contexts(self, fnname, stated, actual):
        import os.path

        filename = os.path.join(self.funcdir, fnname + self.ext)
        with open(filename, "rb") as f:
            content = f.read()

        target = "#context: %s" % stated
        if target in content:
            print("Rewriting", filename)
            with open(filename, "wb") as f:
                f.write(content.replace(target, "#context: %s" % actual))
        else:
            print("Context %s not found in %s, actual=%s"
                  % (stated, fnname, actual))


class GlobalVar(object):
    # (Read/Write)  vector Cf
    def __init__(self, type_, name, readable, writable):
        self.type = type_
        self.name = name
        self.readable = readable
        self.writable = writable

    def __repr__(self):
        return "<Global %s %s (%s%s)>" % (
            self.type.name, self.name,
            "R" if self.readable else "", "W" if self.writable else "",
        )

    def __eq__(self, other):
        return (
            type(self) is type(other) and
            self.name == other.name and
            self.readable == other.readable and
            self.writable == other.writable
        )

    def __hash__(self):
        return (
           hash(self.type) ^
           hash(self.name) ^
           hash(self.readable) ^
           hash(self.writable)
        )

    # @classmethod
    # def parse(cls, line):
    #     m = cls.exp.match(line)
    #     if m:
    #         readable = "Read" in m.group(1)
    #         writable = "Write" in m.group(1)
    #         type_ = TypeAtom.parse(m.group(2))
    #         name = m.group(3)
    #         return cls(type_, name, readable, writable)
    #     else:
    #         raise NoMatch(cls, line, 0, cls.exp.pattern)


class VexChecker(object):
    def __init__(self, reporter=None):
        self.reporter = reporter or PrintReporter()

        # Set of all context names
        self.all_contexts = set()
        # Maps context name -> set of vcc -X signatures in that context
        self.signatures = defaultdict(set)
        # Maps context name -> set of documented signatures in that context
        self.documents = defaultdict(set)
        # Set of documented names that are actually statements
        self.statement_docs = set()
        # Set of function names of deprecated functions
        self.deprecated = set()
        # Maps function name -> contexts the functions appears in
        self.fn_to_contexts = defaultdict(set)
        # Maps context name -> set of functions in that context
        self.context_to_fns = defaultdict(set)
        # Maps context name -> set of globals in that context
        self.globals = defaultdict(set)
        # Maps context name -> set of parsed globals from docs
        self.global_docs = {}
        # Maps statement name -> contexts the statement is allowed in
        self.statements = defaultdict(set)

    def add_signature(self, context, sig):
        fnname = sig.ident.name
        if sig not in self.signatures[fnname]:
            self.signatures[fnname].add(sig)
        self.context_to_fns[context].add(fnname)
        self.fn_to_contexts[fnname].add(context)
        self.reporter.parsed_signature(context, sig)

    def _parse_vcc_context_output(self, context, cjson):
        # Ingest global variables
        for name, data in cjson.get("globals", {}).items():
            gtype = VexType.parse(data["type"])
            gvar = GlobalVar(gtype, name, data["read"], data["write"])
            self.globals[context].add(gvar)

        # Ingest functions
        for fnname, fnlist in cjson.get("functions", {}).items():
            ident = Identifier(fnname)
            for fndata in fnlist:
                rtype = VexType.parse(fndata["return"])

                arglist = []
                for typestring in fndata.get("args", ()):
                    # A parameter is "out" if it the string starts with "export"
                    # or it *doesn't* start with "const"... sigh
                    isout = True
                    if typestring.startswith("const "):
                        typestring = typestring[6:]
                        isout = False
                    elif typestring.startswith("export "):
                        typestring = typestring[7:]
                        isout = True

                    argtype = VexType.parse(typestring)
                    arglist.append(Argument(argtype, isout,
                                            MissingIdentifier()))

                if fndata.get("variadic"):
                    variad = VariadicArgs(fndata.get("variadic_pair"))
                    arglist.append(variad)

                sig = Signature(rtype, ident, ArgumentList(arglist))

                if fndata.get("deprecated"):
                    self.deprecated.add(sig)
                    continue

                self.add_signature(context, sig)

    def parse_vcc_output(self, vccpath):
        # Get the names of the available contexts
        output = check_output([vccpath, "--list-context-json"])
        contexts = json.loads(output)
        self.all_contexts = set(contexts)

        # Get the info for each function in each context
        for context in contexts:
            output = check_output([vccpath, "--list-context-json=" + context])
            cjson = json.loads(output)
            self._parse_vcc_context_output(context, cjson)

    @staticmethod
    def _wiki_pages(pages, path_prefix):
        for filename in sorted(pages.store.list_dir(path_prefix)):
            if not (
                filename == "index.txt" or
                (filename.startswith("_") and not(filename.startswith("__")) ) or
                not filename.endswith(".txt")
            ):
                yield (filename.replace(".txt", ""),
                       pages.json(path_prefix + filename))

    def _process_context_page(self, ctxname, json):
        from bookish import functions

        attrs = json.get("attrs", {})
        if attrs.get("type") != "vexcontext":
            return

        if ctxname == "cop":
            ctxname = "cop2"

        if ctxname not in self.all_contexts:
            self.reporter.extra_context(ctxname)

        self.global_docs[ctxname] = globs = set()
        globalsect = functions.first_subblock_of_type(json,
                                                      "globals_section")
        if globalsect:
            for gblock in functions.find_items(globalsect, "globals_item"):
                attrs = gblock.get("attrs", {})
                name = functions.string(gblock.get("text", ""))
                type_ = TypeAtom.parse(attrs.get("type", ""))
                modestring = attrs.get("mode", "rw")
                readable = "r" in modestring
                writable = "w" in modestring
                globs.add(GlobalVar(type_, name, readable, writable))

    def _process_function_page(self, fnname, json):
        from bookish import functions

        attrs = json.get("attrs", {})
        if attrs.get("type") != "vex":
            return

        contexts = attrs.get("context", attrs.get("contexts", ""))
        self.check_contexts(fnname, contexts)

        if fnname in self.statements:
            self.statement_docs.add(fnname)
            return

        if attrs.get("status") == "deprecated":
            self.reporter.marked_deprecated(fnname)
            if fnname in self.signatures:
                del self.signatures[fnname]
            elif fnname not in self.deprecated:
                self.reporter.extra_doc(fnname)

        # This becomes True if there is at least one usage not marked ignore
        # or deprecated
        valid_usages = False
        for usage in functions.find_items(json, "usage"):
            uattrs = usage.get("attrs", {})
            ustatus = uattrs.get("status", "").strip()
            if ustatus == "ignore":
                continue

            sigstring = functions.string(usage.get("text"))
            try:
                sig = Signature.parse(sigstring)
            except NoMatch as e:
                self.reporter.parser_error(fnname, sigstring, e)
                continue

            if ustatus == "deprecated":
                # TODO: Check that this function is really marked deprecated
                # in the vcc output (check it matches a sig in self.deprecated)
                self.reporter.marked_deprecated(sig)
                continue

            valid_usages = True

            if fnname != sig.ident.name:
                self.reporter.wrong_function_name(fnname, sigstring)

            self.documents[fnname].add(sig)
            self.reporter.parsed_doc_sig(sig)

        # The doc had valid usages, but there was no corresponding function in
        # the vcc output, so issue a warning
        if valid_usages and fnname not in self.signatures:
            self.reporter.extra_doc(fnname)

        self.reporter.parsed_doc_page(fnname)

    def parse_vex_docs(self, app):
        from bookish import flaskapp

        pages = flaskapp.get_wikipages(app)

        for ctxname, json in self._wiki_pages(pages, "/vex/contexts/"):
            self._process_context_page(ctxname, json)

        for fnname, json in self._wiki_pages(pages, "/vex/functions/"):
            self._process_function_page(fnname, json)

    def context_set_to_string(self, contextset):
        if contextset == self.all_contexts:
            string = "all"
        elif contextset == SHADING_CONTEXT_SET:
            string = "shading"
        else:
            string = " ".join(sorted(contextset))
        return string

    def string_to_context_set(self, string):
        if string == "shading":
            contextset = set(SHADING_CONTEXTS)
        elif string == "all":
            contextset = self.all_contexts
        elif not string:
            contextset = set()
        else:
            contextset = set(re.split("[, \t]+", string))

        if "cop" in contextset:
            contextset.remove("cop")
            contextset.add("cop2")

        return contextset

    def check_contexts(self, fnname, contexts):
        stated_contexts = self.string_to_context_set(contexts)

        if fnname in self.statements:
            actual_contexts = self.statements[fnname]
        else:
            actual_contexts = self.fn_to_contexts[fnname]

        actual_string = self.context_set_to_string(actual_contexts)
        if actual_string and stated_contexts != actual_contexts:
            self.reporter.wrong_contexts(fnname, contexts, actual_string)

    def compare_function_names(self):
        sigset = set(self.signatures)
        docset = set(self.documents)

        for missing_fn in sigset - docset:
            self.reporter.missing_doc(
                missing_fn,
                self.context_set_to_string(self.fn_to_contexts[missing_fn]),
            )

        for extra_doc in docset - sigset - self.deprecated:
            self.reporter.extra_doc(extra_doc)

    def match_signatures(self, fnname):
        reporter = self.reporter
        vccsigs = self.signatures[fnname]
        docsigs = self.documents.get(fnname)
        if not docsigs:
            return

        used_patterns = set()
        for vccsig in vccsigs:
            for docsig in docsigs:
                matched = docsig.matches(vccsig)
                reporter.compared_signatures(docsig, vccsig, matched)
                if matched:
                    used_patterns.add(docsig)
                    break
            else:
                reporter.missing_doc_signature(fnname, vccsig, docsigs)

        for unused in docsigs - used_patterns:
            reporter.extra_doc_signature(fnname, unused)

    def match_globals(self):
        for context in sorted(self.all_contexts):
            for missing in self.globals[context] - self.global_docs[context]:
                self.reporter.missing_global(missing, context)

            for extra in self.global_docs[context] - self.globals[context]:
                self.reporter.extra_global(extra, context)

    def match_all_signatures(self):
        for fnname in sorted(self.signatures):
            self.match_signatures(fnname)

    def check_statements(self):
        for statename in self.statements:
            if statename in IGNORE_STATEMENTS:
                continue

            if statename not in self.statement_docs:
                self.reporter.missing_statement_doc(statename,
                                                    self.statements[statename])

    def build(self, vccpath, app):
        from time import time

        self.reporter.start(self)

        self.parse_vcc_output(vccpath)
        self.parse_vex_docs(app)

        self.compare_function_names()
        self.match_all_signatures()
        self.check_statements()
        self.match_globals()

        self.reporter.finish(self)

    def undocumented(self):
        return set(self.signatures) - set(self.documents)

    def overdocumented(self):
        return set(self.documents) - set(self.signatures)


if __name__ == "__main__":
    from houdinihelp.server import get_houdini_app

    # print(Signature.parse("int[]|string[] geoself( )", doc_mode=True))
    # print(Signature.parse("int|string uniqueval( <geometry>, string attribclass, string attribute_name, int which)", doc_mode=True))

    checker = VexChecker()
    app = get_houdini_app(dev=True)
    with app.app_context():
        checker.build("/Users/matt/dev/hfs/bin/vcc", app)




