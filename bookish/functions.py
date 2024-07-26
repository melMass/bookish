# Copyright 2014 Matt Chaput. All rights reserved.
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

import copy
import inspect
import random
import re
from collections import deque

from bookish import paths
from bookish.compat import string_type, text_type, xrange


class Missing(object):
    pass


sentence_end = re.compile(r"([.]\s)|$")


# Context functions

def string(obj, before=None, after=None):
    """
    Converts the kinds of things you might get in a template to unicode.
    If it's a string, returns the string. If it's a list, recursively calls
    string() on the contents and joins them. If it's a dictionary with a "text"
    key, calls string() on that. Otherwise, returns str(obj).
    """

    if obj is None:
        s = ""
    elif isinstance(obj, string_type):
        s = obj
    elif isinstance(obj, (list, tuple)) or inspect.isgenerator(obj):
        s = "".join(string(o, before=before, after=after) for o in obj)
    elif isinstance(obj, dict) and ("text" in obj or "body" in obj):
        s = "".join((string(obj.get("text"), before=before, after=after),
                     string(obj.get("body"), before=before, after=after)))
    else:
        s = str(obj)

    return (before or "") + s + (after or "")


def first(obj):
    if isinstance(obj, (string_type, list, tuple)) and obj:
        yield obj[0]
    elif inspect.isgenerator(obj):
        for x in obj:
            yield x
            break
    else:
        yield obj


def last(obj):
    if isinstance(obj, (string_type, list, tuple)) and obj:
        yield obj[-1]
    elif inspect.isgenerator(obj):
        x = Missing
        for x in obj:
            pass
        if x is not Missing:
            yield x
    else:
        yield obj


def sort(obj, key=None):
    if isinstance(obj, (list, tuple)) or inspect.isgenerator(obj):
        return iter(sorted(obj, key=key))
    else:
        return iter([obj])


def split_tags(tagstring):
    return re.findall("[^ \t\r\n,]+", tagstring)


def find_items(block, itemtype="item"):
    body = None
    if isinstance(block, dict):
        body = block.get("body")
    elif isinstance(block, (tuple, list)):
        body = block

    if body:
        for subblock in body:
            assert isinstance(subblock, dict), ("Found %r in body %r" %
                                                (subblock, body))
            stype = subblock.get("type")
            srole = subblock.get("role")
            matched = ((itemtype and stype == itemtype) or
                       (not itemtype and srole == "item"))
            if matched:
                yield subblock
            else:
                for x in find_items(subblock, itemtype):
                    yield x


def find_links(block):
    body = None
    if isinstance(block, dict):
        for span in block.get("text", ()):
            if isinstance(span, dict) and span.get("type") == "link":
                yield span
        body = block.get("body")
    elif isinstance(block, (list, tuple)):
        body = block

    if body:
        for subblock in body:
            for link in find_links(subblock):
                yield link


def find_spans_of_type(text, typename):
    if isinstance(text, dict):
        text = text.get("text", ())

    for span in text:
        if isinstance(span, dict):
            if span.get("type") == typename:
                yield span
            elif "text" in span:
                for subspan in find_spans_of_type(span, typename):
                    yield subspan


def find_title(block):
    if isinstance(block, (list, tuple)):
        for subblock in block:
            title = find_title(subblock)
            if title:
                return title
        return

    if "title" in block:
        return block["title"]
    elif block.get("type") in ("title", "h"):
        return block.get("text", "")


def first_subblock_text(block):
    for subblock in block.get("body", ()):
        text = subblock.get("text")
        if text:
            return text


def first_subblock_string(block):
    text = first_subblock_text(block)
    if text:
        return string(text)


def subblocks_summary(block):
    for subblock in block.get("body", ()):
        text = string(subblock.get("text"))

        if subblock.get("type") == "summary":
            return text

        m = sentence_end.search(text)
        if m:
            text = text[:m.end()]

        return text

    return ""


def subblocks_of_type(body, typename):
    if isinstance(body, dict):
        body = body.get("body", ())

    for subblock in body:
        if subblock.get("type") == typename:
            yield subblock


def first_subblock_of_type(body, typename):
    for subblock in subblocks_of_type(body, typename):
        return subblock


def _filter_predicate(spec):
    if isinstance(spec, str):
        spec = frozenset(spec.split())

    def predicate_fn(block):
        typename = block.get("type")
        blockid = block_id(block)
        return (typename in spec or
                (blockid and ("#%s" % blockid) in spec))

    return predicate_fn


def retain_subblocks(body, include):
    if isinstance(body, dict):
        body = body.get("body", ())
    pred = _filter_predicate(include)
    return [b for b in body if pred(b)]


def remove_subblocks(body, exclude):
    if isinstance(body, dict):
        body = body.get("body", ())
    pred = _filter_predicate(exclude)
    return [b for b in body if not pred(b)]


def first_span_of_type(text, typename):
    if isinstance(text, dict):
        text = text.get("text", ())

    for span in text:
        if isinstance(span, dict) and span.get("type") == typename:
            return span


def subblock_by_id(body, idstring):
    if isinstance(body, dict):
        body = body.get("body", [])

    for subblock in body:
        if subblock.get("id") == idstring:
            return subblock

        attrs = subblock.get("attrs", {})
        if attrs.get("id") == idstring:
            return subblock


def text_replace(text, target, replacement):
    if isinstance(text, string_type):
        return text.replace(target, replacement)
    elif isinstance(text, (list, tuple)):
        out = []
        for span in text:
            if isinstance(span, string_type):
                span = out.append(span.replace(target, replacement))
            elif isinstance(span, dict) and "text" in span:
                span = span.copy()
                span["text"] = text_replace(span["text"], target, replacement)

            out.append(span)
        return out
    else:
        raise ValueError

def string_before(text, marker):
    text = string(text)
    pos = text.find(marker)
    return text[:pos] if pos >= 0 else text


def string_after(text, marker):
    text = string(text)
    pos = text.find(marker)
    return text[pos + len(marker):] if pos >=0 else text


def next_table_cell(block):
    body = block.get("body", [])
    for subblock in body:
        t = subblock.get("type")
        if t == "cell_group":
            return next_table_cell(subblock)
        elif t == "cell":
            return subblock


def find_all_depth(obj):
    if isinstance(obj, dict):
        yield obj
        if "text" in obj:
            for span in find_all_depth(obj["text"]):
                yield span
        if "body" in obj:
            for block in find_all_depth(obj["body"]):
                yield block
    elif isinstance(obj, (tuple, list)):
        for x in obj:
            for y in find_all_depth(x):
                yield y


def find_all_breadth(obj, with_text=False):
    todo = deque([obj])
    while todo:
        obj = todo.popleft()

        if isinstance(obj, dict):
            if with_text and "text" in obj:
                todo.extend(obj["text"])
            elif "body" in obj:
                todo.extend(obj["body"])
            yield obj


def find_by_attr(top, name, value):
    for b in find_all_depth(top):
        if name == "id" and string(b.get("id")) == value:
            yield b
        elif "attrs" in b and string(b["attrs"].get(name)) == value:
            yield b


def find_with_attr(top, name):
    for b in find_all_depth(top):
        if "attrs" in b and name in b["attrs"]:
            yield b


def first_by_attr(top, name, value):
    for b in find_by_attr(top, name, value):
        return b


def find_by_type(top, typename):
    for b in find_all_depth(top):
        if b.get("type") == typename:
            yield b


def first_of_type(top, typename):
    for b in find_by_type(top, typename):
        return b


def attr(block, name, default=None):
    if block and "attrs" in block:
        return block["attrs"].get(name, default)
    return default


def topattr(block, name, default=None):
    if block:
        if name in block:
            return block[name]
        elif "attrs" in block:
            return block["attrs"].get(name, default)
    return default


def find_id(top, value):
    return first_by_attr(top, "id", value)


def find_headings(block, depth=1, types=("h", "section", "heading")):
    if isinstance(block, dict):
        body = block.get("body", ())
    elif isinstance(block, list):
        body = block
    else:
        raise ValueError("Can't find headings in %r" % block)

    ls = []
    for subblock in body:
        if subblock.get("type") in types or subblock.get("role") in types:
            hblock = copy.copy(subblock)
            hblock["id"] = block_id(subblock)
            if "body" in hblock:
                del hblock["body"]

            if depth > 1 and "body" in subblock:
                hbody = find_headings(subblock, depth-1, types)
                if hbody:
                    hblock["body"] = hbody

            ls.append(hblock)

        elif "body" in subblock:
            ls.extend(find_headings(subblock, depth, types))

    return ls


def build_toc(docroot, basepath=None, block=None, i=0, depth=0, maxdepth=99):
    # If this is the "top" call, create a block to return
    block = block or {"type": "toc", "is_container": True}
    parents = docroot.get("parents")
    if not parents:
        return block

    # i is an index into the list of parents; it increases as we descend through
    # ancestors toward the current page

    # Get the "current" parent
    p = parents[i]
    # Copy the parent's attrs onto the block
    block.setdefault("attrs", {})
    block["attrs"].update(p["attrs"])

    # Copy the subtopics body into the block's body
    subtopics = p["subtopics"]
    if subtopics:
        block["body"] = copy.deepcopy(subtopics.get("body"))
    else:
        block["body"] = []

    if depth < maxdepth:
        # Let's get recursive all up in here
        for item in find_items(block["body"], "subtopics_item"):
            link = first_span_of_type(item.get("text"), "link")
            if not link:
                continue
            fullpath = link.get("fullpath")

            found = False
            if basepath and fullpath == basepath:
                item["is_here"] = True
                st = subblock_by_id(docroot, "subtopics")
                if st:
                    item["body"] = st.get("body", ())
            else:
                for j in xrange(i + 1, len(parents)):
                    if parents[j]["basepath"] == fullpath:
                        item["is_ancestor"] = True
                        build_toc(docroot, basepath, item, j, depth + 1,
                                  maxdepth)
                        found = True
                        break
            if found:
                break

    return block


def icon_ref(val):
    if not paths.extension(val):
        val += ".svg"

    if any(val.startswith(pre) for pre in ("/", "./", "../", "opdef:")):
        return val
    else:
        return "/icons/%s" % val


def has_option(s, key):
    if s:
        return key in string(s).split()


random_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def random_name(length=5):
    charcount = len(random_chars)
    return "".join(random_chars[random.randint(0, charcount)]
                   for _ in xrange(length))


def random_id():
    return "id%05d" % random.randint(0, 99999)


def slugify(text, lower=True):
    from unicodedata import normalize

    if not isinstance(text, text_type):
        text = text.decode("utf8")
    if lower:
        text = text.lower()
    text = normalize("NFKD", text)
    return "-".join(m.group(0) for m
                    in re.finditer(r"\w+", text, re.UNICODE))


def block_id(block, strip_nums=False):
    blockid = block.get("id")
    if not blockid:
        attrs = block.get("attrs")
        if attrs:
            blockid = attrs.get("id")

    if blockid:
        right = len(blockid) - 1
        while strip_nums and right >= 0 and blockid[right].isnumeric():
            right -= 1
        blockid = blockid[:right + 1]

    if blockid:
        return blockid

    text = string(block.get("text"))
    if text:
        return slugify(text)

    return "id" + hex(id(block))[2:]


def collapse(body, types=()):
    newbody = []
    for block in body:
        if "body" in block:
            block["body"] = collapse(block["body"], types)

    for block in body:
        if block.get("type") in types:
            if "body" in block:
                newbody.extend(block["body"])
        else:
            newbody.append(block)

    return newbody


def thing(x):
    return repr(x) + "," + type(x).__name__


def attr_bag(block, attrname):
    if "attrs" in block:
        value = block["attrs"].get(attrname)
        if value:
            return set(value.strip().split(" "))
    return ()


def engroup(blocks):
    blocks = list(blocks)
    if not blocks:
        return None

    type = blocks[0].get("type")
    return {
        "type": type + "_group",
        "body": blocks,
        "container": True,
    }


all_functions = (
    string, first, last, sort, split_tags, find_items, attr, topattr,
    first_subblock_text, first_subblock_string, subblocks_summary,
    first_subblock_of_type, retain_subblocks, remove_subblocks,
    find_title, find_links, first_span_of_type, find_spans_of_type,
    subblock_by_id, text_replace, string_before, string_after,  next_table_cell,
    find_all_depth, find_all_breadth, find_by_attr, find_with_attr,
    first_by_attr, find_by_type, first_of_type, find_headings,
    build_toc, has_option, random_name, random_id, slugify, block_id,
    collapse, thing, icon_ref, attr_bag,
)
functions_dict = dict((fn.__name__, fn) for fn in all_functions)
