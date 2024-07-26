# Copyright 2014 Matt Chaput. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
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

from textwrap import dedent

from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from pygments.formatters.html import escape_html
from pygments.style import Style
from pygments.token import Keyword, Name, Comment, String, Error, \
    Literal, Number, Operator, Other, Punctuation, Text, Generic, \
    Whitespace
from pygments.util import ClassNotFound

from bookish import functions, util


def jinja_format_code(block, lexername=None, pre=False, extras=None):
    from markupsafe import Markup

    html = format_block(block, lexername=lexername, pre=pre, extras=extras)
    return Markup(html)


def lexer_for(name):
    try:
        lexer = get_lexer_by_name(name)
    except ClassNotFound:
        lexer = None
    return lexer


def format_block(block, lexername=None, lexer=None, pre=False, extras=None):
    attrs = block.get("attrs", {})
    source = functions.string(block.get("text", ""))
    look = attrs.get("display", "")
    lexername = lexername or block.get("lang")

    if lexername and not lexer:
        if extras and lexername in extras:
            lexer = extras[lexername]
            if isinstance(lexer, type):
                lexer = lexer()

    if "linenos" in attrs and attrs["linenos"] == "true":
        look += " linenos"

    if "hl_lines" in attrs:
        hl_lines = [int(n) for n
                    in attrs["hl_lines"].strip("[]").split(",")]
    else:
        hl_lines = None

    return format_string(source, lexername, lexer, look, hl_lines, pre)


def format_string(source, lexername=None, lexer=None, look="",
                  hl_lines=None, pre=False):
    source = dedent(source.strip("\r\n"))
    lexer = lexer or lexer_for(lexername)
    if lexer:
        hi = highlight(source, lexer, HtmlFormatter())
        hi = hi.removeprefix('<div class="highlight"><pre>')
        hi = hi.removesuffix('</pre></div>\n')
    else:
        hi = escape_html(source)

    if pre:
        hi = "<pre class='syntax %s'>%s</pre>" % (look, hi)

    return hi


# Command line colors

def code_chars(code):
    return "\033[%sm" % str(code)


class Ansi(object):
    black = code_chars(30)
    red = code_chars(31)
    green = code_chars(32)
    yellow = code_chars(33)
    blue = code_chars(34)
    magenta = code_chars(35)
    cyan = code_chars(36)
    white = code_chars(37)
    reset = code_chars(39)

    black_back = code_chars(40)
    red_back = code_chars(41)
    green_back = code_chars(42)
    yellow_back = code_chars(43)
    blue_back = code_chars(44)
    magenta_back = code_chars(45)
    cyan_back = code_chars(46)
    white_back = code_chars(47)
    reset_back = code_chars(49)

    bright = code_chars(1)
    dim = code_chars(2)
    normal = code_chars(22)
    reset_all = code_chars(0)


def cstring(code, string):
    return code + string + Ansi.reset_all


class DraculaStyle(Style):
    background_color = "#282a36"
    default_style = ""

    styles = {
        Comment: "#6272a4",
        Comment.Hashbang: "#6272a4",
        Comment.Multiline: "#6272a4",
        Comment.Preproc: "#ff79c6",
        Comment.Single: "#6272a4",
        Comment.Special: "#6272a4",

        Generic: "#f8f8f2",
        Generic.Deleted: "#8b080b",
        Generic.Emph: "#f8f8f2 underline",
        Generic.Error: "#f8f8f2",
        Generic.Heading: "#f8f8f2 bold",
        Generic.Inserted: "#f8f8f2 bold",
        Generic.Output: "#44475a",
        Generic.Prompt: "#f8f8f2",
        Generic.Strong: "#f8f8f2",
        Generic.Subheading: "#f8f8f2 bold",
        Generic.Traceback: "#f8f8f2",

        Error: "#f8f8f2",

        Keyword: "#ff79c6",
        Keyword.Constant: "#ff79c6",
        Keyword.Declaration: "#8be9fd italic",
        Keyword.Namespace: "#ff79c6",
        Keyword.Pseudo: "#ff79c6",
        Keyword.Reserved: "#ff79c6",
        Keyword.Type: "#8be9fd",

        Literal: "#f8f8f2",
        Literal.Date: "#f8f8f2",

        Name: "#f8f8f2",
        Name.Attribute: "#50fa7b",
        Name.Builtin: "#8be9fd italic",
        Name.Builtin.Pseudo: "#f8f8f2",
        Name.Class: "#50fa7b",
        Name.Constant: "#f8f8f2",
        Name.Decorator: "#f8f8f2",
        Name.Entity: "#f8f8f2",
        Name.Exception: "#f8f8f2",
        Name.Function: "#50fa7b",
        Name.Label: "#8be9fd italic",
        Name.Namespace: "#f8f8f2",
        Name.Other: "#f8f8f2",
        Name.Tag: "#ff79c6",
        Name.Variable: "#8be9fd italic",
        Name.Variable.Class: "#8be9fd italic",
        Name.Variable.Global: "#8be9fd italic",
        Name.Variable.Instance: "#8be9fd italic",

        Number: "#bd93f9",
        Number.Bin: "#bd93f9",
        Number.Float: "#bd93f9",
        Number.Hex: "#bd93f9",
        Number.Integer: "#bd93f9",
        Number.Integer.Long: "#bd93f9",
        Number.Oct: "#bd93f9",

        Operator: "#ff79c6",
        Operator.Word: "#ff79c6",

        Other: "#f8f8f2",

        Punctuation: "#f8f8f2",

        String: "#f1fa8c",
        String.Backtick: "#f1fa8c",
        String.Char: "#f1fa8c",
        String.Doc: "#f1fa8c",
        String.Double: "#f1fa8c",
        String.Escape: "#f1fa8c",
        String.Heredoc: "#f1fa8c",
        String.Interpol: "#f1fa8c",
        String.Other: "#f1fa8c",
        String.Regex: "#f1fa8c",
        String.Single: "#f1fa8c",
        String.Symbol: "#f1fa8c",

        Text: "#f8f8f2",

        Whitespace: "#f8f8f2"
    }
