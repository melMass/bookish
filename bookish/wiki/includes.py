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

from pygments.lexers import get_lexer_for_filename

from bookish import functions, paths, stores


logger = logging.getLogger("bookish.includes")


# Exceptions

class CircularIncludeError(Exception):
    pass


# Helper functions

def make_include(ref, name=None, value=None, unwrap=None,
                 retain=None, remove=None,
                 newtype=None, newid=None):
    d = dict(type="include", ref=ref, name=name, value=value, unwrap=unwrap,
             retain=retain, remove=remove)
    if newtype:
        d["newtype"] = newtype
    if newid:
        d["newid"] = newid
    return d


def denull(blocks):
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.get("type") == "null":
            blocks[i:i + 1] = block.get("body", [])
            continue
        elif block.get("body"):
            denull(block["body"])
        i += 1


# Include functions

def get_raw_source(block, context, root):
    attrs = block.get("attrs", {})
    if "path" not in attrs:
        return []
    srcpath = paths.join(context["path"], attrs["path"])
    pages = context["pages"]
    # lang = context.lang()
    content = pages.content(srcpath)
    if content:
        lang = (attrs.get("lang")
                or get_lexer_for_filename(srcpath).name)
        return [{
            "type": "pre",  # "lang": lang,
            "text": [content]
        }]
    else:
        logger.warning("Source code not found %s", srcpath)


def parse_include_path(incpath):
    name = value = None
    unwrap = False
    if not incpath:
        return None, None, None, None

    incpath, _, frag = incpath.partition("#")
    if frag:
        if frag.endswith("/"):
            unwrap = True
            frag = frag[:-1]
        if "=" in frag:
            name, value = frag.split("=", 1)
        else:
            name = "id"
            value = frag

    return incpath, name, value, unwrap


def spec_from_path(basepath, ref):
    srcpath, name, value, unwrap = parse_include_path(ref)
    if srcpath:
        # Absolutize the path if given
        srcpath = paths.join(basepath, srcpath)

    # Create a unique key for this include so we can check for circular
    # includes
    key = "%s#%s=%s" % (srcpath, name, value)
    finder = get_finder(name, value)
    return srcpath, finder, key, unwrap


def spec_from_block(block, basepath):
    # Look at the include block and decide what we're looking for. Returns the
    # path of the included file, an optional function to find a specific block
    # in that file, a key representing this particular include, and a boolean
    # whether to "unwrap" the block (include the block's body instead of the
    # block itself).

    # In the far-flung future, it would be interesting to build in a "search
    # engine" that lets you include whatever blocks match a nested set of
    # criteria.

    ref = functions.topattr(block, "ref") or functions.topattr(block, "ext")
    if ref is None:
        raise ValueError("Include block %r has null ref" % (block,))

    srcpath, name, value, unwrap = parse_include_path(ref)
    if srcpath:
        # Absolutize the path if given
        srcpath = paths.join(basepath, srcpath)

    # If the block has name and value attrs, override the values from the ref
    _name = functions.topattr(block, "name")
    _value = functions.topattr(block, "value")
    if _name is not None and _value is not None:
        name, value = _name, _value

    # If the block has an unwrap attr, override the value from the ref
    _unwrap = functions.topattr(block, "unwrap")
    if _unwrap is not None:
        unwrap = _unwrap

    # Create a unique key for this include so we can check for circular
    # includes
    key = "%s#%s=%s" % (srcpath, name, value)
    finder = get_finder(name, value)
    return srcpath, finder, key, unwrap


def get_finder(name, value):
    finder = None
    if name:
        if name == "id":
            def finder(root):
                return functions.find_id(root, value)
        elif name == "type":
            def finder(root):
                return functions.engroup(functions.find_items(root, value))
        else:
            def finder(root):
                return functions.first_by_attr(root, name, value)
    return finder


def get_included(block, context, root):
    thispath = context["path"]
    srcpath, finder, key, unwrap = spec_from_block(block, thispath)

    icontent = None
    if srcpath and srcpath != paths.basepath(thispath):
        # The include is in another page
        icontent = load_include(block, context, root)
        if not icontent:
            logger.warning("Include not found: %s", key)
    elif finder:
        # If no path was given, or it's this page's path, grab the target from
        # this page
        icontent = target(root, finder, unwrap)
        if not icontent:
            logger.warning("Local include not found: %s", key)

    if icontent and len(icontent) == 1:
        # Apply "newtype" and "newid" attrs
        newtype = functions.topattr(block, "newtype")
        if newtype:
            icontent[0]["type"] = newtype
        newid = functions.topattr(block, "newid")
        if newid:
            icontent[0]["id"] = newid

    retain = functions.topattr(block, "retain")
    if icontent and retain:
        icontent = functions.retain_subblocks(icontent, retain)

    remove = functions.topattr(block, "remove")
    if icontent and remove:
        icontent = functions.remove_subblocks(icontent, remove)

    if icontent:
        denull(icontent)

    return icontent


def load_include(block, context, root):
    # Manages the include history to look out for circular includes before
    # actually loading the included content

    path, finder, key, unwrap = spec_from_block(block, context["path"])
    return load_include_impl(path, finder, key, unwrap, context, root)


def load_include_path(basepath, ref, context, root):
    path, finder, key, unwrap = spec_from_path(basepath, ref)
    return load_include_impl(path, finder, key, unwrap, context, root)


def load_include_impl(path, finder, key, unwrap, context, root):
    # Check if the unique key is already in the include history stored in
    # the context
    history = context.get("include_history", frozenset())
    if key in history:
        raise CircularIncludeError(
            "Trying to import %s with import history %r" % (key, history)
        )

    # In case of recursive includes, create a new context that adds this
    # to the include history
    newhistory = history.union([key])
    icontext = context.push({"include_history": newhistory,
                             "including": True,
                             "path": path})

    # Load the included file, from the include cache if possible
    icache = context.top().setdefault("include_cache", {})
    if icache and path in icache:
        incdata = copy.deepcopy(icache[path])
    else:
        try:
            pages = context["pages"]
            # lang = context["lang"]
            incdata = pages.json(path, icontext, postprocess=False)
        except stores.ResourceNotFoundError:
            return None
        icache[path] = incdata

    assert incdata["type"] == "root"

    # Add the current path to the list of included paths
    incd = set(root.get("included", ()))
    incd.add(path)
    # Add any recursively included paths in the included file
    if "included" in incdata:
        incd |= set(incdata["included"])
    # Record the list of included paths on the root
    root["included"] = sorted(incd)

    # The target function takes care of finding a fragment
    return target(incdata, finder, unwrap)


def target(root, finder, unwrap):
    if finder:
        block = finder(root)
        if not block:
            return None

        if unwrap:
            return block.get("body")
        else:
            return [block]
    else:
        return root["body"]





