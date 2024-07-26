# Copyright 2013 Matt Chaput. All rights reserved.
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

from __future__ import print_function

import copy
import logging
import re
import sys
from collections import defaultdict

from bookish import functions, paths, util
from bookish.compat import StringIO
from bookish.compat import iteritems, string_type
from bookish.wiki import includes, langpaths
from bookish.util import join_text


logger = logging.getLogger(__name__)


# Base classes

class Processor(object):
    """
    Base class for objects that walk a document tree modifying the blocks in
    place.
    """

    name = ""

    def __repr__(self):
        return "<%s:%s>" % (type(self).__name__, self.name)

    def __or__(self, other):
        return Pipe([self, other])

    def add(self, other):
        return Pipe([self, other])

    def apply(self, block, context):
        pass

    def process_indexed(self, pages, block, doc, cache):
        pass


class Pipe(Processor):
    """
    Processor that wraps multiple processor objects and calls them each in turn.
    """

    def __init__(self, processors):
        self.processors = []
        for v in processors:
            self.add(v)

    def __repr__(self):
        return "<%s %r>" % (type(self).__name__, self.processors)

    def add(self, other):
        if isinstance(other, Pipe):
            for v in other.processors:
                self.add(v)
        elif self.processors and isinstance(other, Modifier):
            last = self.processors[-1]
            if isinstance(last, MultiModifier):
                last.add(other)
            elif isinstance(last, Modifier):
                self.processors[-1] = MultiModifier([last, other])
            else:
                self.processors.append(other)
        elif isinstance(other, Processor):
            self.processors.append(other)
        else:
            raise Exception("Can't add %s %r to pipeline"
                            % (type(other), other))

    def processor_by_class(self, cls):
        for proc in self.processors:
            if isinstance(proc, cls):
                return proc

    def apply(self, block, context, profile=False, threshold=0.1):
        if context.get("profiling"):
            path = context["path"]
            proc_times = context["proc_time"]
            proc_list = proc_times.setdefault(path, [])
        else:
            proc_list = None

        for v in self.processors:
            t = util.perf_counter()
            v.apply(block, context)
            if proc_list is not None:
                proc_list.append((v.name or repr(v), util.perf_counter() - t))
            if profile:
                pt = util.perf_counter() - t
                if pt >= threshold:
                    print("    ::Processor=", v, pt)

    def process_indexed(self, pages, block, doc, cache):
        for v in self.processors:
            v.process_indexed(pages, block, doc, cache)


class TreeProcessor(Processor):
    """
    Middle-ware for processors that might have to process every block in the
    tree. Does the work of traversing the tree, calling `modify(block, context)`
    at each block. If the `modify` method returns `True`, the processor
    recursively processes each child of the block.
    """

    def apply(self, block, context):
        if self.modify(block, context):
            body = block.get("body", ())
            if body:
                for subblock in body:
                    self.apply(subblock, context)

    def modify(self, block, context):
        raise NotImplementedError


class MultiModifier(Processor):
    """
    Processor that wraps multiple Modifier objects. This object walks the document
    tree and calls each modifier on each block.
    """

    def __init__(self, modifiers):
        self.modifiers = modifiers

    def __repr__(self):
        return "<%s %r>" % (type(self).__name__, self.modifiers)

    def add(self, modifier):
        self.modifiers.append(modifier)

    def apply(self, block, context):
        for m in self.modifiers:
            m.apply(block, context)
        for subblock in block.get("body", ()):
            self.apply(subblock, context)


class Modifier(Processor):
    """
    A type of Processor that only modifies a single block at a time (that is,
    that doesn't care about hierarchy). This allows them to be grouped together
    in a MultiModifier.
    """

    def modify(self, block, context):
        raise NotImplementedError

    def apply(self, block, context):
        self.modify(block, context)
        body = block.get("body", ())
        for subblock in body:
            if not isinstance(subblock, dict):
                raise Exception("body contains %r" % subblock)
            self.apply(subblock, context)


# Block processors

class Title(Processor):
    """
    Finds the page title and summary blocks and copies their text up to the root
    for easier access by other code.
    """

    name = "title"

    def apply(self, block, context):
        for subblock in block.get("body", ()):
            sbtype = subblock.get("type")
            if sbtype == "title":
                block["title"] = subblock.get("text")
            elif sbtype == "summary":
                block["summary"] = subblock.get("text")


class Hierarchy(Processor):
    """
    Organizes a linear list of blocks into a hierarchy based on the relative
    values of a key (usually "indent").
    """

    name = "hierarchy"

    def __init__(self, attr="indent", default=0):
        """
        :param attr: The key to use to determine the hierarchical level of
            a given block.
        :param default: The value to use for blocks that don't have the
            attribute key.
        """

        self.attr = attr
        self.default = default

    def apply(self, block, context):
        attr = self.attr
        default = self.default

        body = block.get("body")
        if body:
            newbody = []
            lastvalue = None
            lastblock = None

            for subblock in body:
                if not subblock:
                    continue

                value = subblock.get(attr, default)
                if lastblock is not None and value > lastvalue:
                    if "body" not in lastblock:
                        lastblock["body"] = []

                    lastblock["body"].append(subblock)
                    lastblock["container"] = True
                else:
                    newbody.append(subblock)
                    lastblock = subblock
                    lastvalue = value
            block["body"] = newbody

            if newbody:
                for subblock in newbody:
                    self.apply(subblock, context)


class SortHeadings(Processor):
    """
    Implements "linear" header style, where blocks simply come after headers at
    the same indent, instead of being indented under the heading. This processor
    looks for headings without bodies and pulls any subsequent blocks into them.
    """

    name = "sortheadings"
    after = ("hierarchy", "promote")

    def apply(self, block, context):
        body = block.get("body")
        if not body:
            return

        newbody = []
        inheading = False
        currentlevel = None
        for sb in body:
            assert sb is not block

            if sb.get("container") and "level" in sb:
                # This is a heading
                level = sb["level"]

                if inheading and level > currentlevel:
                    # If we're currently collecting under a previous heading,
                    # and this heading is under that one, move it into the
                    # previous heading's body
                    newbody[-1]["body"].append(sb)
                elif sb.get("body"):
                    # This heading already has its own (indent) content, so
                    # don't try collecting subsequent blocks into it
                    inheading = False
                    newbody.append(sb)
                else:
                    # If this heading doesn't already have its own body, start
                    # collecting subsequent blocks at this level under the
                    # heading
                    if "body" not in sb:
                        sb["body"] = []
                    newbody.append(sb)
                    inheading = True
                    currentlevel = level
            else:
                if inheading:
                    newbody[-1]["body"].append(sb)
                else:
                    newbody.append(sb)
        block["body"] = newbody

        if newbody:
            for subblock in newbody:
                self.apply(subblock, context)


class Groups(Processor):
    """
    Groups blocks of the same type "N" under "group_N" superblocks.
    """

    name = "groups"
    after = ("hierarchy", "sections")

    def __init__(self, types=("bullet", "ord", "dt", "item"),
                 blacklist=("billboard", "null")):
        """
        :param whitelist: if not empty, only type names in this collection
            will be grouped.
        :param blacklist: if not empty, no type names in this collection will
            be grouped.
        """

        self.types = frozenset(types)
        self.blacklist = frozenset(blacklist)

    def apply(self, block, context):
        # if context.get("include_history"):
        #     return

        body = block.get("body")
        if not body:
            return

        newbody = []
        current = None

        # Note that this algorithm needs to deal with groups already existing
        # in the data because of includes
        for subblock in body:
            typename = subblock.get("type", "")
            role = subblock.get("role", "")
            groupname = typename + "_group"

            if typename not in self.blacklist and (typename in self.types or
                                                   role in self.types):
                # This block is of a type that should be grouped
                self.apply(subblock, context)

                # If this is not type of the current grouping, start a new
                # group and push it onto the new body
                if groupname != current:
                    group = {"type": groupname, "body": [], "container": True}
                    if role:
                        group["role"] = "%s_group" % role
                    newbody.append(group)
                # Put the block in the group at the end of the new body
                newbody[-1]["body"].append(subblock)
                # This block's type is now the current grouping
                current = groupname

            # This block is a group that's the same as the current grouping
            elif current is not None and typename and typename == current:
                # Move the items in this group into the group at the end of the
                # new body
                newbody[-1]["body"].extend(subblock["body"])
                # Don't need to change current here

            # This block is a group
            elif typename.endswith("_group") and subblock.get("container"):
                newbody.append(subblock)
                # Make this the current grouping
                current = typename

            # This is some other kind of block
            else:
                self.apply(subblock, context)
                newbody.append(subblock)
                # Reset the grouping to None
                current = None

        block["body"] = newbody


class Properties(Processor):
    """
    Changes "property" blocks into attributes on the parent block.
    Make sure this runs after Hierarchy.
    """

    name = "properties"
    after = ("sortheadings",)

    def apply(self, block, context):
        body = block.get("body")
        if body:
            newbody = []
            for subblock in body:
                if subblock.get("type") == "prop":
                    name = subblock["name"]
                    value = subblock.get("value")
                    if "attrs" in block:
                        attrs = block["attrs"]
                    else:
                        attrs = block["attrs"] = {}
                    attrs[name] = value
                else:
                    newbody.append(subblock)
                    self.apply(subblock, context)

            block["body"] = newbody


class EmptyBlocks(Processor):
    """
    Removes blocks without any content. Ignores certain things.
    """

    name = "empty"

    @staticmethod
    def _can_be_empty(block):
        return (
            block.get("container")
            or block.get("role") == "item"
            or block.get("type") in ("xml", "pxml", "divider", "sep")
        )

    @staticmethod
    def _no_text(block):
        text = block.get("text", ())
        if not text:
            return True

        # Return True if the sequence contains all strings, but all the strings
        # are empty. This covers semi-common cases such as [""].
        if all(isinstance(x, string_type) for x in text) and\
                not any(x for x in text):
            return True

        return False

    def apply(self, block, context):
        body = block.get("body")
        if body:
            i = 0
            while i < len(body):
                sb = body[i]

                nobody = not sb.get("body")
                notext = self._no_text(sb)
                if nobody and notext and not self._can_be_empty(sb):
                    del body[i]
                    continue

                self.apply(sb, context)
                i += 1


class Promote(Processor):
    """
    Finds blocks where a bit of xml or an include is the only thing in the
    block, and "promotes" that span up to block level.
    """

    name = "promote"

    def apply(self, block, context):
        body = block.get("body")
        if not body:
            return

        for i, subblock in enumerate(body):
            subtype = subblock.get("type")

            if subtype in ("para", "bullet"):
                spans = subblock.get("text")
                if spans:
                    # Ignore empty strings
                    spans = [s for s in spans
                             if (isinstance(s, dict) or
                                 functions.string(s).strip())]
                    if len(spans) == 1 and isinstance(spans[0], dict):
                        only = spans[0]
                        otype = only.get("type")
                        oscheme = only.get("scheme")
                        is_xml = otype == "xml"
                        is_include = ((otype == "link" and oscheme == "Include")
                                      or otype == "include")

                        if (subtype == "para" and is_xml) or is_include:
                            # Replace this block with the XML or include inside
                            subbody = subblock.get("body")
                            if subbody:
                                only["body"] = subbody
                            subblock = body[i] = only

            self.apply(subblock, context)


class Sections(Processor):
    """
    Sets the "text" on sections if it wasn't given, and changes the "type" of
    plain items inside a section to a type based on the section name. For
    example, a plain item inside a `@properties` section becomes type
    `properties_item`.
    """

    name = "sections"
    after = ("hierarchy",)

    def apply(self, block, context, itemtype=None):
        # If this is a section...
        if block.get("role") == "section":
            # Give it a title if it doesnt have one
            if not block.get("text"):
                block["text"] = functions.string(block["id"]).capitalize()

            # Take its ID and make an item type from it
            itemtype = block["id"] + "_item"

        blocktype = block.get("type")
        if blocktype == "item" and itemtype:
            # If we're in a section, change this item's type to one based on
            # the section ID
            block["type"] = itemtype

        elif block.get("body"):
            # Recurse inside containers, passing down the item type
            for subblock in block.get("body", ()):
                self.apply(subblock, context, itemtype)


class Includes(Processor):
    """
    Finds include directives and replaces them with the included wiki content.
    """

    name = "includes"
    after = ("promote", "properties")

    def apply(self, block, context):
        # This is called on the root block and doesn't recurse... instead it
        # calls _replace_includes which recurses on both blocks (body) and
        # spans (text)

        if context.get("noinclude") or not context.get("path"):
            return
        self._replace_includes(block.get("body", ()), context, block)

    def _replace_includes(self, objs, context, root):
        # This is generic so it can work on a list of spans (text) or blocks
        # (body)

        # Operate on indices so Python doesn't complain about changing a list
        # while iterating over it
        i = 0
        while i < len(objs):
            sub = objs[i]
            if not isinstance(sub, dict):
                i += 1
                continue

            # If this is an include link, convert it to an include block/span
            # before proceeding
            if sub.get("type") == "link" and sub.get(
                    "scheme") == "Include":
                sub = {"type": "include", "ref": sub.get("value")}

            stype = sub.get("type")
            icontent = None
            if stype == "source":
                icontent = includes.get_raw_source(sub, context, root)
            elif stype == "include":
                icontent = includes.get_included(sub, context, root)

            if icontent:
                # Splice the content into the block list
                objs[i:i + 1] = icontent
                # ...then move the pointer to after the spliced-in content
                i += len(icontent)
            else:
                # Recurse on this object's text and/or body
                text = sub.get("text")
                body = sub.get("body")
                if text and not isinstance(text, string_type):
                    self._replace_includes(text, context, root)
                if body:
                    self._replace_includes(body, context, root)
                i += 1


class Templates(Modifier):
    name = "templates"
    after = ("promote", "properties")

    def apply(self, block, context, defns=None):
        from bookish.util import Context

        ds = None
        if block.get("container") or defns is None:
            ds = self._find_defns(block)

        if defns is None:
            defns = Context(ds)
        elif ds:
            defns = defns.push(ds)

        if defns.has_keys():
            self._apply_defns(block, context, defns)

    def _apply_defns(self, parent, context, defns):
        import json

        i = 0
        body = parent.get("body", ())
        while i < len(body):
            block = body[i]
            if block.get("type") == "block_call":
                defname = functions.string(block.get("text")).strip()
                template = defns.get(defname)
                if template:
                    attrs = block.get("attrs", {})
                    output = template.render(**attrs)
                    jsondata = json.loads(output)

                    if isinstance(jsondata, string_type):
                        jsondata = {"type": "para", "text": [jsondata]}
                    if isinstance(jsondata, dict):
                        jsondata = [jsondata]
                    if isinstance(jsondata, list):
                        if not all(isinstance(d, dict) for d in jsondata):
                            continue
                    else:
                        continue

                    body[i:i+1] = jsondata

            elif block.get("body"):
                self.apply(block, context, defns)

            i += 1

    @staticmethod
    def _find_defns(parent):
        import json
        from jinja2 import Template

        defns = {}
        i = 0
        body = parent.get("body", ())
        while i < len(body):
            block = body[i]
            if block.get("type") == "block_def":
                defname = functions.string(block.get("text")).strip()
                if defname:
                    attrs = block.get("attrs", {})
                    if "template" in attrs:
                        string = attrs["template"].strip()
                    else:
                        string = json.dumps(block.get("body", ()))
                    defns[defname] = Template(string)

            i += 1
        return defns


class Tables(Processor):
    """
    Because of the way simple tables are marked up, you end up with a cell block
    for each row, where each rightward cell is the only child of the cell to its
    left. This processor re-organizes this into a more render-friendly
    structure.
    """

    name = "tables"
    after = ("hierarchy",)

    def apply(self, block, context):
        body = block.get("body")
        if body:
            if any(b.get("type") == "table" for b in body):
                # This block is already done (probably because it's included)
                # so bail out
                return

            if any(b.get("type") == "cell" for b in body):
                newbody = []

                # Find runs of adjacent "cell" blocks in the body
                run = []
                for subblock in body:
                    # If we find a cell, add it to the current run
                    if subblock.get("type") == "cell":
                        run.append(subblock)
                    else:
                        # This is not a cell, so flush the current run
                        if run:
                            # Convert the run to a table block
                            newbody.append(self._run_to_table(run, context))
                            run = []

                        self.apply(subblock, context)
                        newbody.append(subblock)

                if run:
                    newbody.append(self._run_to_table(run, context))

                block["body"] = newbody
            else:
                # No cells here, recurse into the body
                for subblock in body:
                    self.apply(subblock, context)

    def _run_to_table(self, run, context):
        thead = []
        tbody = []

        for cell in run:
            # Convert the recursive structure of cells containing rightward
            # cells into a linear row
            cells = self._cells_to_row(cell, context)
            row = {"type": "row", "body": cells, "divider": False}

            # If all the cells are heading cells, and there hasn't been a body
            # row yet, put this row in the thead
            if all(c.get("role") == "th" for c in cells) and not tbody:
                thead.append(row)
            else:
                last_body = cells[-1].get("body", ())
                if last_body:
                    last_block = last_body[-1]
                    if last_block.get("type") == "sep":
                        del last_body[-1]
                        row["divider"] = True

                tbody.append(row)

        return {"type": "table", "thead": thead, "body": tbody}

    def _cells_to_row(self, cell, context):
        body = cell.get("body")
        left = cell
        if body:
            del left["body"]
            if len(body) == 1 and body[0].get("type") == "cell":
                return [left] + self._cells_to_row(body[0], context)
            else:
                for subblock in body:
                    self.apply(subblock, context)
                return [left, {"type": "cell", "role": "td", "body": body}]
        else:
            return [left]


class RenumberHeadings(Processor):
    """
    Adds "level" keys to headings indicating their level in the heading
    hierarchy.
    """

    name = "renumberheadings"
    after = ("sortheadings", "includes")

    def apply(self, block, context, level=2):
        body = block.get("body", ())
        for subblock in body:
            if subblock.get("type") == "h":
                subblock["level"] = level
                self.apply(subblock, context, level + 1)
            else:
                self.apply(subblock, context, level)


class LinkProcessor(Processor):
    """
    Base class for processors of links.
    """

    def _apply_to_subtopics(self, block, context):
        if "parents" in block:
            for parent in block["parents"]:
                parentpath = parent["path"]
                psubs = parent.get("subtopics")
                if psubs:
                    self.apply(psubs, context, parentpath)

    def apply(self, block, context, basepath=None):
        if block.get("type") == "root":
            self._apply_to_subtopics(block, context)

        basepath = basepath or paths.basepath(context.get("path"))
        if "text" in block:
            self.text(context, block["text"], basepath)

        # Recurse
        for subblock in block.get("body", ()):
            self.apply(subblock, context, basepath)

    def text(self, context, text, basepath):
        for span in text:
            if isinstance(span, dict):
                if span.get("type") == "link":
                    self.link(context, span, basepath)
                elif "text" in span and span["text"]:
                    self.text(context, span["text"], basepath)

    def link(self, context, span, basepath):
        return


class FullPaths(LinkProcessor):
    """
    Finds links in the content, and annotates them with the absolute path to the
    linked page.
    """

    name = "fullpaths"

    def link(self, context, span, basepath):
        pages = context["pages"]

        # Don't bother if this object has already operated on this link
        # (for example, if it was included)
        if "fullpath" in span:
            return

        path = span.get("value")
        if not path or ":" in path:
            span["exists"] = True
            return

        fullpath = pages.full_path(basepath, path)
        span["fullpath"] = fullpath

        pagepath, fragment = paths.split_fragment(fullpath)
        if fragment:
            span["fragment"] = fragment


# Text processors

class TextModifier(Modifier):
    """
    Special subclass of Modifier that only modifies text nodes.
    """

    def modify(self, block, context):
        text = block.get("text")
        if text:
            block["text"] = self.text(text, context)

    def text(self, text, context):
        raise NotImplementedError


class JoinText(TextModifier):
    """
    Joins adjacent runs of text together, so `["foo", "bar"]` becomes
    `["foobar"]`.
    """

    name = "join"

    def text(self, text, context):
        return join_text(text)


class JoinKeys(TextModifier):
    """
    Coalesces consecutive keys spans.
    """

    name = "joinkeys"

    @staticmethod
    def _is_keys(obj):
        return isinstance(obj, dict) and obj.get("type") == "keys"

    def text(self, text, context):
        is_keys = self._is_keys
        i = 0
        if isinstance(text, list):
            while i < len(text):
                if i and is_keys(text[i]) and is_keys(text[i - 1]):
                    prev = text[i - 1]
                    this = text.pop(i)
                    prev["keys"].extend(this["keys"])
                    if "alt_keys" in prev and "alt_keys" in this:
                        prev["alt_keys"] = [
                            pak + tak for pak, tak
                            in zip(prev["alt_keys"], this["alt_keys"])
                        ]
                else:
                    if isinstance(text[i], dict) and "text" in text[i]:
                        self.text(text[i], context)
                    i += 1

        return text


class Shortcuts(TextModifier):
    """
    Finds shortcuts and looks for a method corresponding to the shortcut's
    scheme to process it. You must subclass this to get it to do anything.
    """

    name = "shortcuts"

    @staticmethod
    def _xform_wp(span):
        span["value"] = "http://en.wikipedia.org/wiki/" + span["value"]

    @staticmethod
    def _xform_pill(span):
        del span["scheme"]
        span["type"] = "span"
        span["class"] = "pill %s" % span.get("value", "")

    @staticmethod
    def _xform_image(span):
        span["type"] = "img"

    def text(self, text, context):
        for i, span in enumerate(text):
            if isinstance(span, dict) and span.get("type") == "link":
                scheme = span.get("scheme", "link")
                if scheme:
                    methodname = "_xform_%s" % scheme.lower()
                    if hasattr(self, methodname):
                        getattr(self, methodname)(span)
        return text


# Post processors

class Metadata(Processor):
    """
    Adds some simple metadata to the JSON after it's generated.
    """

    name = "metadata"

    def apply(self, block, context):
        if block.get("type") != "root":
            return
        block["path"] = context["path"]


class AnnotateLinks(LinkProcessor):
    """
    Finds links in the content, looks up the linked document in the search
    index, and adds annotations to the link based on the linked document's
    search fields.
    """

    name = "annotate"
    default_attrs = "title type icon summary container".split()

    def __init__(self, attrs=None):
        self.attrs = self.default_attrs
        if attrs:
            if isinstance(attrs, string_type):
                attrs = attrs.split()
            self.add_attrs(*attrs)

    def add_attrs(self, *attrs):
        self.attrs.extend(attrs)

    def link(self, context, span, basepath):
        # t = util.perf_counter()
        # Don't try to annotate image links
        if span.get("scheme") in ("Image", "Icon", "Smallicon", "Largeicon"):
            return
        pages = context["pages"]
        searcher = context["searcher"]

        # Don't bother if this object has already operated on this link
        # (for example, if it was included).
        # Only operate on links to other wiki pages.
        if "fields" in span or "fullpath" not in span:
            return

        fullpath = paths.strip_extension(span["fullpath"], ".html")
        pagepath, fragment = paths.split_fragment(fullpath)
        spath = pages.source_path(pagepath)
        exists = span["exists"] = pages.exists(spath)

        # Look up the linked page in the index and copy its stored
        # fields onto the link
        if searcher and exists:
            stored = searcher.document(path=fullpath)
            if stored is not None:
                spanfields = span["fields"] = {}
                # Copy the stored fields onto the span
                for attrname in self.attrs:
                    if attrname in stored:
                        spanfields[attrname] = stored[attrname]

                # If the link had no text and the stored page has a title,
                # copy the title to the text
                title = stored.get("title")
                if title and not span.get("text"):
                    span["text"] = [title]

        # If there's fallback_text and no text, and no stored title from the
        # search, copy the fallback_text (if any) to the text
        fbtext = span.get("fallback_text")
        if fbtext and not span.get("text"):
            span["text"] = fbtext
            del span["fallback_text"]

        # lt = util.perf_counter() - t
        # print("      link=", lt)
        # self.t += lt


class RunSearches(Processor):
    """
    Finds various items that run searches and replaces them with the search
    results.
    """

    name = "searches"
    default_fields = "path title summary type icon status tags".split()

    @staticmethod
    def _hit_to_dict(hit, fieldnames):
        return dict((fn, hit.get(fn)) for fn in fieldnames if fn in hit)

    @staticmethod
    def _read_labels(pages, basepath, labelspath, labels):
        labelspath = paths.join(basepath, labelspath)
        labelspath, section = paths.split_fragment(labelspath)
        section = section[1:] if section else "Labels"

        if pages.exists(labelspath):
            content = pages.content(labelspath, encoding="utf-8")
            bio = StringIO(content)
            import configparser
            parser = configparser.ConfigParser()
            parser.read_file(bio)
            if parser.has_section(section):
                labels.update(dict(parser.items(section)))

    @staticmethod
    def get_results(block, context):
        attrs = block.get("attrs", {})
        searcher = context["searcher"]
        if searcher is None:
            return

        q = searcher.query()
        if "query" not in attrs:
            block["error"] = "No query property"
            return
        q.set(attrs["query"])

        if "limit" in attrs:
            limstring = attrs["limit"]
            try:
                limit = int(limstring)
            except ValueError:
                limit = None
            q.set_limit(limit)

        if "sortedby" in attrs:
            fieldnames = attrs["sortedby"].split()
            for fieldname in fieldnames:
                rev = False
                if fieldname.startswith("-"):
                    fieldname = fieldname[1:]
                    rev = True
                q.add_sort_field(fieldname, rev)

        if "groupedby" in attrs:
            groupfield = attrs["groupedby"].strip()
            overlap = attrs.get("overlap", "").lower() == "true"
            q.set_group_field(groupfield, overlap)

        # By default, search in the same language as the page is in
        langattr = attrs.get("lang")
        if not langattr:
            langname = context["lang"]
        elif langattr == "*":
            langname = None
        else:
            langname = langattr

        # Rewrite path queries to be language-aware
        # for leafq in q.q.leaves():
        #     if leafq.field() == "path":
        #         if not lang.has_lang(leafq.text):
        #             leafq.text = lang.enlang(langname, leafq.text)
        # print("q=", q.q)

        return q.search(lang=langname)

    @classmethod
    def _run_search(cls, context, basepath, block, icache):
        pages = context["pages"]
        searcher = context["searcher"]
        if searcher is None:
            return

        path = context["path"]
        attrs = block.get("attrs", {})
        if not attrs:
            return

        r = cls.get_results(block, context)
        if r and not r.is_empty():
            if "groupedby" in attrs:
                labels = block["labels"] = {}
                if "labels" in attrs:
                    cls._read_labels(pages, path, attrs["labels"], labels)

                groups = block["groups"] = {}
                for key, docnums in iteritems(r.groups()):
                    if not key:
                        key = u"_"
                    groups[key] = searcher.group_hits(docnums)
            else:
                hits = []
                for hit in r:
                    d = hit.fields()
                    # path = d["path"]
                    # if path == basepath:
                    #     d["is_here"] = True

                    # if include_content:
                    #     spath = pages.source_path(path)
                    #     json = pages.json(spath, postprocess=False)
                    #     if json:
                    #         d["body"] = json.get("body")

                    hits.append(d)
                block["hits"] = hits

    @staticmethod
    def _similarly_tagged(root, context):
        searcher = context["searcher"]

        attrs = root.get("attrs", {})
        showtags = attrs.get("showtags")
        if showtags != "true":
            return

        pagetype = attrs.get("type")
        if not pagetype:
            return

        tagstring = attrs.get("tags")
        if tagstring:
            section = functions.first_subblock_of_type(root, "related_section")
            if not section:
                body = root.setdefault("body", [])
                section = {
                    "type": "related_section", "role": "section",
                    "id": "related", "level": 1, "container": True,
                }
                body.append(section)

            results = {}
            tags = [tagname.strip() for tagname in tagstring.split(",")]
            for tagname in tags:
                tagged = searcher.tagged_documents(tagname, pagetype)
                results[tagname] = tagged
            section["tagged"] = results

    def apply(self, block, context, root=None):
        searcher = context["searcher"]
        if not searcher:
            return
        basepath = paths.basepath(context.get("path"))
        root = root or block

        for parent in block.get("parents", ()):
            psubs = parent.get("subtopics")
            if psubs:
                self.apply(psubs, context, root)

        if block.get("type") == "root":
            self._similarly_tagged(block, context)

        if block.get("type") == "list" or functions.topattr(block, "is_search"):
            icache = {}
            self._run_search(context, basepath, block, icache)
        else:
            for subblock in block.get("body", ()):
                self.apply(subblock, context, root)


class Parents(Processor):
    """
    Annotates the current document with information about its parent documents,
    including their subtopics, allowing the template to display things like
    breadcrumbs and a tree view.
    """

    name = "parents"

    @staticmethod
    def _find_ancestor(pages, dirpath):
        # Look for an _index file in the given directory, and if not found,
        # recursively look in parent directories

        spath = None
        while True:
            spath = pages.source_path(dirpath)
            if pages.exists(spath):
                return spath
            elif dirpath != "/":
                dirpath = paths.parent(dirpath)
                continue
            break

        return spath

    @staticmethod
    def get_parent_path(pages, path, block):
        # Find the path to the parent document

        attrs = block.get("attrs", {})
        if "parent" in attrs:
            # If the author specified a parent, use that (if it exists)
            parent = attrs.get("parent")
            parentpath = pages.source_path(paths.join(path, parent))
            if pages.exists(parentpath):
                return parentpath

        if pages.is_index_page(path):
            # If this is an index page, assume its parent is the _index page of
            # the parent directory
            parentpath = Parents._find_ancestor(pages, paths.parent(path))

        else:
            # Assume the parent is the _index page for this directory
            parentpath = Parents._find_ancestor(pages, paths.directory(path))

        return parentpath

    def apply(self, block, context):
        if context.get("no_page_nav"):
            return

        # Only run on the root block
        if block.get("type") != "root":
            return
        # Don't bother getting parents if this is an include
        if context.get("including"):
            return

        root = block

        # Get needed objects and options from the context
        pages = context["pages"]
        path = context["path"]

        # A list of dictionaries containing ancestor doc info
        pcontext = context.push({"noinclude": True})
        parentpath = self.get_parent_path(pages, path, block)
        parents = pages.parent_info_list(parentpath, pcontext,
                                         self.get_parent_path)

        # Note that we should copy/relist the parent list so we don't interfere
        # with any cache
        if parents:
            # Reverse the list so it's in descending order
            parents = parents[::-1]
        else:
            parents = []

        # Attach the parent JSON and list of parents to the root
        root["parents"] = parents


class Toc(Processor):
    name = "toc"
    before = ("annotate",)

    @staticmethod
    def _apply(context, item, basepath, depth, maxdepth):
        pages = context["pages"]

        # Find the first link in the item and use its path
        text = item.get("text")
        link = functions.first_span_of_type(text, "link")
        if not link:
            return
        ref = link.get("value")
        if not ref or ":" in ref:
            return

        fullpath = pages.full_path(basepath, ref)
        if not pages.exists(fullpath):
            return

        # Load the referenced page
        json = pages.json(fullpath, context)
        # Find the subtopics section
        subtopics = functions.subblock_by_id(json, "subtopics")
        if not subtopics:
            return

        # Copy the subtopics onto this topic's body
        if "body" in subtopics:
            body = copy.deepcopy(subtopics["body"])
            # Collapse certain block types
            body = functions.collapse(body, ("col_group", "col"))
            item["body"] = body

        if depth < maxdepth:
            # Recurse on the loaded subtopics
            topics = functions.find_items(subtopics, "subtopics_item")
            for subitem in topics:
                Toc._apply(context, subitem, fullpath, depth + 1, maxdepth)

    def apply(self, block, context):
        basepath = paths.basepath(context.get("path"))

        # Find the subtopics section
        subtopics = functions.subblock_by_id(block, "subtopics")
        if not subtopics:
            return

        attrs = subtopics.get("attrs", {})
        maxdepth = int(attrs.get("maxdepth", "0"))
        if not maxdepth:
            return

        topics = functions.find_items(subtopics, "subtopics_item")
        for item in topics:
            self._apply(context, item, basepath, 1, maxdepth)


class BackLinks(Processor):
    name = "backlinks"
    before = ("annotate", )

    def apply(self, block, context):
        searcher = context.get("searcher")
        if not searcher:
            return

        section = functions.first_subblock_of_type(block, "backlinks_section")
        if section:
            body = section.setdefault("body", {})
            path = paths.basepath(context["path"])
            for fields in searcher.documents(links=path):
                body.append({
                    "type": "backlink",
                    "text": [{"type": "link", "fullpath": fields["path"]}]
                })


class Flow(Processor):
    name = "flow"
    after = ("annotate",)

    def apply(self, block, context):
        from bookish.wiki import includes

        attrs = block.get("attrs")
        if not attrs or "flow" not in attrs:
            return
        flowref = attrs["flow"]
        path = context["path"]
        searcher = context.get("searcher")
        basepath = paths.basepath(path)
        flowjson = includes.load_include_path(basepath, flowref, context, block)
        if not flowjson:
            return

        # Find the flow title
        block["flow_title"] = functions.find_title(flowjson)

        # Find the flow links
        links = list(functions.find_links(flowjson))
        block["flow_links"] = links
        for i, link in enumerate(links):
            linkpath = paths.strip_extension(link.get("fullpath"), ".html")

            if searcher:
                link["fields"] = searcher.document(path=linkpath)

            if linkpath == basepath:
                block["flow_index"] = i
                if i > 0:
                    block["previous"] = links[i - 1]
                if i < len(links) - 1:
                    block["next"] = links[i + 1]

        # Insert blocks to trigger display of the flow
        body = block.setdefault("body", [])
        i = 0
        while i < len(body) and body[i].get("type") in ("title", "summary"):
            i += 1
        body.insert(i, {"type": "flow"})
        body.append({"type": "flow"})


class DeleteNotImplemented(Processor):
    name = "deleteni"
    after = ("properties",)

    def apply(self, block, context, root=True):
        if root:
            pagetype = functions.attr(block, "type")
            if pagetype not in ("hompackage", "hommodule", "homclass"):
                return

        body = block.get("body", ())
        i = 0
        while i < len(body):
            subblock = body[i]
            status = functions.attr_bag(subblock, "status")
            if "ni" in status:
                del body[i]
            else:
                self.apply(subblock, context, root=False)
                i += 1


class PythonAPI(Processor):
    name = "postpythonapi"
    before = ("annotate",)

    def apply(self, block, context):
        attrs = block.get("attrs", {})
        pagetype = attrs.get("type")
        if pagetype == "pypackage":
            self._package(block, context, attrs)
        elif pagetype == "pyclass":
            self._class(block, context, attrs)
        elif pagetype == "pymodule":
            self._module(block, context, attrs)
        elif pagetype == "pyfunction":
            self._function(block, context, attrs)

        searcher = context["searcher"]
        if searcher:
            self._links(block, context)

    def _pyname(self, block):
        attrs = block.get("attrs")
        if attrs and "py_anchor" in attrs:
            return attrs["py_anchor"]
        title = block["title"]
        return functions.string(title).strip()

    def process_indexed(self, pages, block, doc, cache):
        doctype = doc.get("type")
        if doctype in ("pypackage", "pyclass", "pymodule", "pyfunction",
                       "hompackage", "homclass", "hommodule", "homfunction"):
            doc["category"] = "pyscripting"
            if "py_anchor" not in doc:
                doc["py_anchor"] = self._pyname(block)

            pkgcache = cache.setdefault("py_parent", {})
            path = doc["path"]
            anchor = doc.get("py_anchor").lower()
            if anchor:
                dirpath = paths.directory(path)
                if dirpath in pkgcache:
                    pkgs = pkgcache[dirpath]
                else:
                    settings = pages.store.settings(dirpath)
                    if settings.has_section("Python"):
                        pkgs = dict((k, settings.get("Python", k)) for k
                                    in settings.options("Python"))
                        pkgcache[dirpath] = pkgs
                    else:
                        pkgs = {}

                parts = anchor.split(".")
                if doctype in ("pypackage", "hompackage"):
                    parts = parts[:-1]
                for i in range(len(parts), 0, -1):
                    name = ".".join(parts[:i])
                    if name in pkgs:
                        doc["py_parent"] = "%s %s" % (name, pkgs[name])
                        break

    def _links(self, block, context):
        if "text" in block:
            self._text(block["text"], context)

        body = block.get("body", ())
        for subblock in body:
            self._links(subblock, context)

    def _package(self, block, context, attrs):
        block["subtitle"] = " package"

    def _page_methods(self, block):
        section = functions.subblock_by_id(block, "methods")
        if section:
            for methblock in functions.find_items(section, "methods_item"):
                text = functions.string(methblock.get("text"))
                bracket = text.find("(")
                if bracket >= 0:
                    name = text[:bracket]
                else:
                    modes = functions.attr_bag(methblock, "mode")
                    if "prop" not in modes:
                        attrs = methblock.get("attrs")
                        if not attrs:
                            attrs = methblock["attrs"] = {}
                        attrs["mode"] = attrs.get("mode", "") + " prop"
                    name = text
                yield name, methblock

    def _class(self, block, context, attrs):
        block["subtitle"] = " class"

        searcher = context["searcher"]
        if not searcher:
            return
        pyname = self._pyname(block)
        if not pyname:
            return

        # Annotate subclasses
        subclasses = []
        for subdoc in searcher.documents(superclass=pyname):
            subclasses.append({
                "title": subdoc.get("title"),
                "path": subdoc.get("path"),
                "summary": subdoc.get("summary"),
            })
        subclasses.sort(key=lambda d: d["title"])
        block["subclasses"] = subclasses

        # Get names of methods on this class
        methodnames = set(name for name, _ in self._page_methods(block))

        # Find the superclasses
        supers = list(self._superclasses(context, methodnames, block))
        if not supers:
            return

        # If there isn't already a methods section, create one to hold the
        # superclass headings
        methods = functions.subblock_by_id(block, "methods")
        if not methods:
            methodsbody = []
            methods = {"type": "methods_section", "id": "methods",
                       "containter": True, "role": "section",
                       "body": methodsbody}
            block["body"].append(methods)
        else:
            methodsbody = methods["body"]

        # Include superclasses
        for path, title, supermethods in reversed(supers):
            # Don't create a heading if there aren't any methods on this class
            if not supermethods:
                continue

            # Generate the heading text
            # TODO: how to translate this?
            text = [
                "Methods from ",
                {"type": "link", "fullpath": path, "text": title}
            ]

            # Attributes for the generated heading: don't index the contents
            # (they're indexed on their original page), add a glyph to make it
            # clearer these are superclass methods
            attrs = {"index": "no", "glyph": "fa-angle-double-up"}

            # Generate the heading block to hold the method blocks
            heading = {"type": "h", "text": text, "attrs": attrs,
                       "container": True, "role": "heading",
                       "body": supermethods,
                       "level": 2, "super_path": path, "super_title": title,
                       }
            methodsbody.append(heading)

        block["superclasses"] = [
            {"path": path, "title": title}
            for path, title, _ in supers
        ]

    def _superclasses(self, context, methodnames, block, history=None):
        # Recursively loads the doc pointed to by the block's "superclass"
        # attribute and yields a (path, rootblock) pair for each superclass

        searcher = context["searcher"]
        pages = context["pages"]
        history = history or set()
        attrs = block.get("attrs")
        if attrs and "superclass" in attrs:
            superclass = attrs.get("superclass").strip()
            superdoc = searcher.document(py_anchor=superclass)
            if not superdoc:
                return
            spath = superdoc["path"]

            if pages.exists(spath):
                if spath in history:
                    raise Exception("Circular superclass structure")
                else:
                    history.add(spath)

                superjson = pages.json(spath, context, postprocess=False)
                title = superjson.get("title", superclass)

                # Find the method items on the superclass
                methods = []
                for name, methblock in self._page_methods(superjson):
                    # If this name is in the set of seen methods, it's
                    # overridden, so we should skip it
                    if name in methodnames:
                        continue

                    methodnames.add(name)
                    methods.append(methblock)

                yield spath, title, methods
                for x in self._superclasses(context, methodnames, superjson,
                                            history):
                    yield x

    def _module(self, block, context, attrs):
        block["subtitle"] = " module"

        prefix = self._pyname(block)
        section = functions.subblock_by_id(block, "values")
        if section:
            for valblock in functions.find_items(section, "values_item"):
                valblock["prefix"] = prefix

    def _function(self, block, context, attrs):
        block["subtitle"] = " function"

    def _text(self, text, context):
        for span in text:
            # Only look at links
            if not (isinstance(span, dict) and span.get("type") == "link"):
                continue

            scheme = span.get("scheme")
            value = span.get("value")
            fragment = span.get("fragment")
            if scheme == "Py" and value:
                hashpos = value.find("#")
                pyname = value[:hashpos] if hashpos >= 0 else value

                brackets = False
                if fragment and fragment.endswith("()"):
                    brackets = True
                    fragment = span["fragment"] = fragment[:-2]

                if "py_anchor_cache" in context:
                    cache = context["py_anchor_cache"]
                else:
                    cache = context["py_anchor_cache"] = {}

                if pyname in cache:
                    stored = cache[pyname]
                else:
                    searcher = context["searcher"]
                    stored = searcher.document(py_anchor=pyname)
                    cache[pyname] = stored

                if stored and "path" in stored:
                    span["fullpath"] = stored["path"]
                    if fragment:
                        span["fullpath"] += fragment

                if not span.get("text"):
                    text = pyname
                    if fragment:
                        text += fragment.replace("#", ".")
                        if brackets:
                            text += "()"
                    span["text"] = text

                #
                # if scheme == "Py":
                #     fb = (fullpath + fragment).replace("/", ".").replace("#", ".")
                #     span["fallback_text"] = fb
                #
                #     searcher = context["searcher"]
                #     stored = searcher.document(py_anchor=fullpath)
                #     if stored is not None and "path" in stored:
                #         span["fullpath"] = stored["path"]


# Defaults

default_preprocessor_classes = (
    JoinText,
    Title,
    Hierarchy,
    Properties,
    DeleteNotImplemented,
    Shortcuts,
    Promote,
    SortHeadings,
    Sections,
    Templates,
    Includes,
    EmptyBlocks,
    RenumberHeadings,
    Groups,
    Tables,
    FullPaths,
    JoinKeys,
)

default_postprocessor_classes = (
    Metadata,
    Parents,
    RunSearches,
    # Toc,
    BackLinks,
    AnnotateLinks,
    Flow,
    PythonAPI,
)


# Dependency graph

class CircularDependencyError(Exception):
    pass


class DependencyGraph(object):
    def __init__(self, vs=None):
        self._vs = vs or []
        self._vset = set(self._vs)
        self._prereqs = defaultdict(set)
        self._resolved = set()
        self._unresolved = set()

    def add(self, v):
        if v not in self._vset:
            self._vset.add(v)
            self._vs.append(v)

    def depends_on(self, v, prereq):
        if v not in self._vset:
            self.add(v)
        if prereq not in self._vset:
            self.add(prereq)
        self._prereqs[v].add(prereq)

    def resolve(self, vs=None):
        vs = vs or self._vs
        for v in vs:
            if v in self._resolved:
                continue
            if v in self._unresolved:
                raise CircularDependencyError(v)

            self._unresolved.add(v)
            if v in self._prereqs:
                prevs = list(self._prereqs[v])
                prevs.sort(key=lambda x: self._vs.index(x))
                for prev in self.resolve(prevs):
                    yield prev

            self._unresolved.remove(v)
            self._resolved.add(v)
            yield v


def make_pipeline(objs):
    # Add the object names to the DG, retaining their incoming order
    dg = DependencyGraph([obj.name for obj in objs])
    # Create a dict to look up objects by their names
    byname = dict((obj.name, obj) for obj in objs)

    # For each object, look at its before and after attributes and add them
    # to the DG
    for obj in objs:
        for aftname in getattr(obj, "after", ()):
            dg.depends_on(obj.name, aftname)
        for befname in getattr(obj, "before", ()):
            dg.depends_on(befname, obj.name)

    # Resolve the dependencies
    resolved_names = dg.resolve()
    # Create a pipe from the objects in resolved order
    return Pipe([byname[name] for name in resolved_names])


def default_pre_pipeline():
    objs = [cls() for cls in default_preprocessor_classes]
    return make_pipeline(objs)


def default_post_pipeline():
    objs = [cls() for cls in default_postprocessor_classes]
    return make_pipeline(objs)
