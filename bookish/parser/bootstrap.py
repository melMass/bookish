from __future__ import print_function
import os.path
from string import ascii_letters

from bookish.parser import ParserContext
from bookish.parser import rules as r
from bookish.util import find_object

"""
This module "hand-makes" a parser for the bkgrammar format by composing the
low-level parsing objects into a parser.
You can then use that "bootstrapped" parser to parse bkgrammar files as an
easier way to generate parsers.

Originally there was a meta.bkgrammar file that defined a parser to parse
itself, and the hand-made parser was used to parse that (hence "bootstrap"), but
that was too convoluted, so now we just go from the hand-made parser.
"""


# Parser class

def make_namespace(imports, rules, ns=None, snap=True):
    for n, rule in rules.items():
        rule.set_name(n)

    ns = ns or {}
    for n, qid in imports.items():
        ns[n] = find_object(str(qid))
    ns.update(rules)

    for name, rule in rules.items():
        if isinstance(rule, r.Call) and not rule.args:
            rules[name] = ns[name] = ns[rule.name]
    ctx = ParserContext(namespace=ns)
    seen = set()
    for name, rule in rules.items():
        rules[name] = ns[name] = rule.snap(ctx, seen)

    return ns


class Parser:
    def __init__(self, imports, rules, main="grammar", ns=None):
        self.imports = imports
        self.rules = rules
        self.namespace = make_namespace(imports, rules, ns)
        mainrule = self.namespace[main]
        self.main_rule = mainrule

    def context(self):
        return ParserContext(namespace=self.namespace)

    def parse(self, stream, debug=False, pos=0):
        ctx = self.context().set_debug(debug)
        out, i = self.main_rule(stream, pos, ctx)
        assert out is not r.Miss
        return out

    def parse_parser(self, stream, debug=False, pos=0, main="grammar", ns=None):
        imps, rules = self.parse(stream, debug=debug, pos=pos)
        return self.__class__(imps, rules, main=main, ns=ns)

    def as_python_source(self):
        from bookish.parser.builder import Builder

        bld = Builder(self.imports, self.rules, self.main_rule, self.context())
        return bld.run()

    def write_python_file(self, filepath):
        source = self.as_python_source()
        with open(filepath, "wb") as f:
            f.write(source.encode("utf-8"))

    def as_module(self, name):
        from types import ModuleType

        source = self.as_python_source()
        compiled = compile(source, '<string>', 'exec')
        mod = ModuleType(name)
        exec(compiled, mod.__dict__)
        return mod


# Copy base definitions from rules

any_ = r.any_
alphanum = r.alphanum
streamstart = r.streamstart
linestart = r.linestart
lineend = r.lineend
streamend = r.streamend
blockbreak = r.blockbreak


# Supporting definitions

comment = r.Regex("#[^\n]*")
hspace = r.Regex("[ \t]|#[^\n]*")
hspaces = r.Star(hspace)
vspace = r.Regex("\r\n|[\r\n]")
vspaces = r.Star(vspace)
ws = r.Star(hspace | vspace | comment)

emptyline = hspaces + vspace
emptylines = r.Star(emptyline)
indent = r.Star(emptyline) + r.Regex("[ \t]+")
noindent = emptylines + r.Not(r.Peek(r.Regex("[ \t]+")))

digit = r.Among("0123456789")
hexdigit = r.Among("0123456789ABCDEFabcdef")
digits = r.Plus(digit)
letters = r.Among(ascii_letters)

decnum = r.Bind("ds", r.Take(r.Plus(digit))) + r.Do("int(ds)")
hexnum = "0x" + r.Bind("xs", r.Take(r.Plus(hexdigit))) + r.Do("int(x, 16)")
barenum = r.Or(decnum, hexnum)

_number = (
    ws +
    (
        ("-" + barenum + r.Do("-x")) |
        barenum
    )
)

escchar = "\\" + (
    ("n" + r.Value("\n")) ** "lf" |
    ("r" + r.Value("\r")) ** "cr" |
    ("t" + r.Value("\t")) ** "tab" |
    ("b" + r.Value("\b")) ** "bs"|
    ("f" + r.Value("\f")) ** "ff" |
    ("x" + r.Bind("x", r.Take(r.Repeat(hexdigit, 2, 4))) +
     r.Do("chr(int(x, 16))")) ** "hx" |
    any_
)

identifier = r.Regex("[A-Za-z_][A-Za-z_0-9]*")

dqstring = ('"' + r.Wall("dq") + r.Bind("s", r.Mixed('"', escchar)) + '"' +
            r.Do("''.join(s)"))
sqstring = ("'" + r.Wall("sq") + r.Bind("s", r.Mixed("'", escchar)) + "'" +
            r.Do("''.join(s)"))


# Individual parsing rules

string = r.Bind("s", (dqstring | sqstring)) + r.Do("rules.String(s)")

among = ("[" + r.Wall("[") + r.Bind("items", r.Mixed("]", escchar)) + "]" +
         r.Do("rules.Among(''.join(items))"))

firsts = (">[" + r.Wall("+") +
          r.Bind("chars", r.Take(r.Plus(r.Not(r.Peek("]")) + (escchar | any_)))) +
          "]" +
          r.Do("rules.FirstChars(chars)"))

value = ("->" + r.Wall("->") + ws + r.Bind("v", r.value_expr) +
         r.Do("rules.Do(v)"))

action1 = ("!(" + r.Wall("!(") + r.Bind("code", r.action_expr) + ")" +
           r.Do("rules.Do(code)"))

action2 = ("!!(" + r.Wall("!!(") + r.Bind("code", r.action_expr) + ")" +
           r.Do("rules.DoCode(code)"))

predicate1 = ("?(" + r.Wall("?(") + r.Bind("code", r.action_expr) + ")" +
              r.Do("rules.If(code)"))

predicate2 = ("??(" + r.Wall("??(") + r.Bind("code", r.action_expr) + ")" +
              r.Do("rules.IfCode(code)"))

wall_ = "!!" + r.Bind("n", identifier) + r.Do("rules.Wall(n)")

mixed = (
    "@(" + r.Wall("@") +
    r.Bind("until", r.Call("expr1")) +
    r.Bind("target",
           (ws + "," + r.Wall("@,") + ws + r.Call("expr1")) |
           r.Value(None)
           ) +
    ")" +
    r.Do("rules.Mixed(until, target)")
)

fail = (".(" + r.Wall(".(") + r.Bind("frule", r.Call("expr1")) + ")" +
        r.Do("rules.FailIf(frule)"))

extent = ("x(" + ws + r.Wall("extent") + r.Bind("erule", r.Call("expr")) +
          ws + ")" + r.Do("rules.Extent(erule)"))

brackets = ("(" + r.Wall("(") + ws +
            r.Bind("inside", r.Call("expr")) + ws + ")" +
            r.Get("inside"))

take = ("<" + r.Wall("<") + r.Bind("trule", r.Call("expr")) + ws + ">" +
        r.Do("rules.Take(trule)"))

regex = ("/" + r.Wall("regex") + r.Bind("chars", r.Mixed("/")) + "/" +
         r.Do("rules.Regex(''.join(chars))"))

arguments = (
    ("(" + r.Bind("args", r.appargs) + ")" + r.Get("args")) |
    r.Value(())
)

call = (r.Bind("name", identifier) + r.Bind("args", arguments) +
        r.Do("rules.Call(name, args)"))

call2 = (r.Bind("mod", identifier) +
         "." + r.Bind("name", identifier) +
         r.Bind("args", arguments) +
         r.Do("rules.Call2(mod, name, args)"))

# Expressions

atom = (
    string | take | regex | wall_ | value |
    predicate2 | predicate1 | action2 | action1 |
    mixed | among | firsts | brackets | fail | extent | call2 | call
)
expr1 = (("^" + r.Wall("^") + r.Bind("a", atom) + r.Do("rules.LookBehind(a)"))
         | atom)

tildable = (
    ("~~~" + r.Bind("e1", expr1) + r.Do("rules.Not(rules.Peek(e1))")) |
    ("~~" + r.Bind("e1", expr1) + r.Do("rules.Peek(e1)")) |
    ("~" + r.Bind("e1", expr1) + r.Do("rules.Not(e1)")) |
    expr1
)

repeattimes = (
    "{" +
    r.Bind("mn", barenum) +
    r.Bind("mx", (
        (r.Regex(" *, *") + (barenum | r.Value(None))) |
        r.Get("mn")
    )) +
    "}" +
    r.Do("(mn, mx)")
)
repeatable = (
    r.Bind("e2", tildable) +
    (
        ("*" + r.Do("rules.Star(e2)")) |
        ("+" + r.Do("rules.Plus(e2)")) |
        ("?" + r.Do("rules.Opt(e2)")) |
        (r.Bind("ts", repeattimes) + r.Do("rules.Repeat(e2, *ts)")) |
        r.Get("e2")
    ) ** "postfixes"
)

bindable = (
    r.Bind("e3a", repeatable) +
    (
        (r.String(":") + r.Wall("bind") + r.Bind("n", identifier) +
         r.Do("rules.Bind(n, e3a)")) |
        r.Get("e3a")
    )
)

seqable = (
    r.Bind("e3", bindable) +
    r.Bind("e3s", r.Star(
        (hspace | (r.Opt(hspace) + indent)) +
        bindable
    )) +
    r.Do("rules.Seq(e3, *e3s) if e3s else e3")
)

expr = (
    r.Bind("e4", seqable) +
    r.Bind("e4s", r.Star(ws + "|" + ws + seqable)) +
    r.Do("rules.Or(e4, *e4s) if e4s else e4")
)


# Grammar support

dottedname = r.Take(r.Seq(identifier, r.Star(r.Seq(".", identifier))))
import_ = (
    noindent +
    "import " + r.Bind("qid", dottedname) +
    " as " + r.Bind("n", identifier) +
    r.Do("(n, qid)")
)

ruleend = hspaces + (vspaces | r.streamend)
assignment = (
    r.Not(r.streamend) +
    noindent +
    r.Wall("rule") +
    r.Bind("n", identifier) +
    r.Bind("args", arguments) +
    r.Regex(" *= *") +
    r.Bind("e", expr) +
    ruleend +
    r.Do("(n, rules.Params(e, args) if args else e)")
)

grammar = (
    r.Bind("imps", r.Star(import_)) +
    r.Bind("rs", r.Plus(assignment)) +
    ws + r.streamend +
    r.Do("(dict(imps), dict(rs))")
)


# API functions

def make_rule_dict(localdict):
    return dict((n, v.set_name(n)) for n, v in localdict.items()
                if isinstance(v, r.Rule))


rule_dict = make_rule_dict(locals())
boot_parser = Parser({}, rule_dict, ns={"rules": r})


def boot_parse_grammar(filepath, debug=False, pos=0, main="grammar", ns=None):
    with open(filepath, "rb") as f:
        content = f.read().decode("utf-8")
    return boot_parser.parse_parser(content, debug=debug, pos=pos, main=main,
                                    ns=ns)


def parse_grammar_file(filepath, pos=0, main="grammar", ns=None):
    from bookish.grammars import meta

    with open(filepath, "rb") as f:
        content = f.read().decode("utf-8")

    out, _ = meta.grammar(content, pos, ParserContext())
    assert out is not r.Miss
    imps, rules = out
    return Parser(imps, rules)


def compile_grammar_file(inpath, outpath=None, pos=0,
                         main="grammar", ns=None):
    parser = parse_grammar_file(inpath, pos=pos, main=main, ns=ns)

    if not outpath:
        lastdot = inpath.rfind(".")
        assert lastdot >= 0
        outpath = os.path.join(os.path.dirname(inpath),
                               inpath[:lastdot] + ".py")

    parser.write_python_file(outpath)


if __name__ == "__main__":
    # Generate a Python source module from the bootstrap parser defined above
    boot_parser.write_python_file("../grammars/meta.py")

    # Generate a Python source module from the wiki markup grammar
    compile_grammar_file("../grammars/wiki.bkgrammar")

    compile_grammar_file("../grammars/avenue.bkgrammar")

#     import time
#     gpath = "../grammars/wiki.bkgrammar"
#     t = time.time()
#     wp = parse_grammar_file(gpath)
#     # wikimod = wp.as_module("wiki")
#     wp.write_python_file("../grammars/wiki.py")
#     print(time.time() - t)
#
#     t = time.time()
#     from bookish.grammars import wiki
#     print("%0.07f" % (time.time() - t))
#
#     s = """
# *strong with _em_*.
# """
#
#     print(len(s))
#     out, _ = wiki.grammar(s, 0, ParserContext())
#     assert out is not r.Miss
#     for block in out:
#         print(block)

