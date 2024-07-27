from __future__ import print_function
import re
from urllib.parse import urlparse, parse_qs

from bookish import paths, functions, util
from bookish.wiki import langpaths, pipeline, wikipages

table_to_dir = {
    "Object": "obj",
    "Sop": "sop",
    "Particle": "part",
    "Dop": "dop",
    "ChopNet": "chopnet",
    "Chop": "chop",
    "Driver": "out",
    "Shop": "shop",
    "Cop2": "cop2",
    "CopNet": "copnet",
    "Vop": "vop",
    "VopNet": "vex",
    "Top": "top",
    "TopNet": "topnet",
    "Lop": "lop",
    "Manager": "manager",
}


# Setup

def pages_from_config(config, cls=None, jinja_env=None, logger=None):
    store = wikipages.store_from_config(config)
    jinja_env = jinja_from_config(config, store, jinja_env=jinja_env)
    logger = wikipages.logger_from_config(config, logger)

    cls = cls or config.get("PAGES_CLASS", HoudiniPages)
    if isinstance(cls, str):
        cls = util.find_object(cls)

    return cls(store, jinja_env, config, logger=logger)


def jinja_from_config(config, store, jinja_env=None):
    jinja_env = wikipages.jinja_from_config(config, store, jinja_env=jinja_env)

    from houdinihelp import vex
    jinja_env.globals["vex_to_wiki"] = vex.vex_to_wiki

    return jinja_env


# Page manager

class HoudiniPages(wikipages.WikiPages):
    def __init__(self, *args, **kwargs):
        super(HoudiniPages, self).__init__(*args, **kwargs)
        self.use_hou = self.config.get("USE_HOU", True)
        self._setup_pipelines()

    def _setup_pipelines(self):
        # Get the default pre-processors and add Houdini-specific ones
        preprocs = self._pre_pipeline.processors
        preprocs.extend([
            HoudiniNodes(),
            HoudiniShelves(),
            HoudiniShortcuts(self.use_hou),
            ExampleFiles(),
            Itemize(),
            ContentFroms(),
            HoudiniIds(),
            HomTitles(),
            VexPages(),
            RewriteReplaces(),
            Actions(self.use_hou),
        ])

        # Get the default post-processors and add Houdini-specific ones
        postprocs = self._post_pipeline.processors
        postprocs.extend([
            NodeMetadata(self.use_hou),
            HomClasses(),
            Suites(),
            Replacements(),
            ExampleSearches(),
            IconAliases(),
        ])

        # Recompute dependencies and make new pipelines
        self._pre_pipeline = pipeline.make_pipeline(preprocs)
        self._post_pipeline = pipeline.make_pipeline(postprocs)

        # Tell the AnnotateLinks processor to copy Houdini-specific fields onto
        # links
        anno = self._post_pipeline.processor_by_class(pipeline.AnnotateLinks)
        anno.add_attrs("context", "status")

        # print("prepipe=", self._pre_pipeline)
        # print("postpipe=", self._post_pipeline)


class HoudiniPagesWithoutHou(HoudiniPages):
    def __init__(self, *args, **kwargs):
        super(HoudiniPagesWithoutHou, self).__init__(*args, **kwargs)
        self.use_hou = False
        self._setup_pipelines()


# Support functions

scheme_map = {
    "Node": "/nodes/%s",
    "Cmd": "/commands/%s",
    "Exp": "/expressions/%s",
    "Mantra": "/props/mantra#%s",
    "Vex": "/vex/functions/%s",
    "Hweb": "/hwebserver/%s"
}


def get_shortcut(scheme, value):
    # Special case collisions with the index page name
    if value == "index":
        value = "index_"

    if scheme in scheme_map:
        template = scheme_map[scheme]
        if callable(template):
            return template(value)
        else:
            return template % value
    else:
        return value


def parse_shortcut(path):
    if path and path[0] == path[0].upper() and ":" in path:
        scheme, value = path.split(":", 1)
        return get_shortcut(scheme, value)
    else:
        return path


def url_to_path(url):
    if url.startswith("/"):
        # Houdini passed a path instead of a URL, because who cares about what
        # *I* have to deal with?
        return url

    parsed = urlparse(url)

    # parse_qs properly returns a dictionary mapping to LISTS of
    # values, since a query string can have repeated keys, but we don't need
    # that capability so we'll just turn it into a dict mapping to the first
    # value
    qs = dict((key, vallist[0]) for key, vallist
              in list(parse_qs(parsed.query).items()))

    if parsed.scheme in ("op", "operator"):
        table, name = parsed.path.split("/", 1)
        if table.endswith("_state"):
            return "/shelf/" + name

        path = "/nodes/%s/%s" % (table_to_dir.get(table, table), name)
        if "namespace" in qs:
            path = "%s--%s" % (qs["namespace"], path)
        # if "version" in qs:
        #     path = "%s-%s" % (path, qs["version"])
        if "scopeop" in qs:
            path = "%s@%s" % (qs["scopeop"], path)
        if parsed.fragment:
            path = "%s#%s" % (path, parsed.fragment)
        return path

    elif parsed.scheme == "tool":
        return "/shelf/" + parsed.path

    elif parsed.scheme == "help":
        path = parsed.path
        if parsed.fragment:
            path = "%s#%s" % (path, parsed.fragment)
        return path

    # Didn't recognize the URL
    # raise ValueError("Can't convert %r to path" % url)
    return None


# Houdini-specific processors

class HoudiniNodes(pipeline.Processor):
    """
    Sets any missing node-specific information based on HOM calls.
    """

    name = "nodes"
    after = ("properties", "includes")

    def apply(self, block, context):
        path = paths.basepath(context["path"])
        is_index = paths.basename(path) == "index"
        dpath = langpaths.safe_delang(path)
        attrs = block.get("attrs")

        if not dpath.startswith("/nodes/") or is_index:
            return
        if attrs and "type" in attrs and attrs["type"] != "node":
            return

        # Assume if it doesn't have a parameters section it's not a node
        # body = block.get("body", ())
        # parms = functions.first_subblock_of_type(body, "parameters_section")
        # if not parms:
        #     return

        from houdinihelp import (path_to_components, path_to_nodetype,
                                 table_to_dir)

        nodeinfo = path_to_components(dpath)
        if nodeinfo is None:
            return

        # Fill in missing properties from information in path
        attrs = block.setdefault("attrs", {})
        if "type" not in attrs and not is_index:
            attrs["type"] = "node"
        if "context" not in attrs:
            attrs["context"] = table_to_dir[nodeinfo.table]
        if "internal" not in attrs:
            attrs["internal"] = nodeinfo.corename
        if "version" not in attrs:
            attrs["version"] = nodeinfo.version
        if "namespace" not in attrs:
            attrs["namespace"] = nodeinfo.namespace


class HoudiniShelves(pipeline.Processor):
    name = "shelves"

    def __init__(self):
        self._cached = False
        self._sets = {}
        self._tabs = {}
        self._tools = {}

    def _read_xml(self, store):
        if self._cached:
            return

        import time
        import xml.etree.ElementTree as ET

        _sets = {}
        _tabs = {}
        _tools = {}

        # print("Reading XML...")
        t = time.time()
        for fname in store.list_dir("/toolbar/"):
            if not (fname.endswith(".shelf") or fname.endswith(
                    ".master_shelf")):
                continue
            path = "/toolbar/" + fname
            root = ET.fromstring(store.content(path))
            if root.tag != "shelfDocument":
                continue
            for child in root:
                if child.tag == "tool":
                    name = child.attrib["name"]
                    helpurl = child.findtext("helpURL")
                    path = url_to_path(helpurl) if helpurl else None
                    icon = child.attrib.get("icon")
                    icon = icon.replace("_", "/", 1) if icon else None
                    _tools[name] = {
                        "name": name,
                        "label": child.attrib["label"],
                        "icon": icon,
                        "help_url": helpurl,
                        "path": path,
                    }
                elif child.tag == "toolshelf":
                    toolnames = []
                    name = child.attrib["name"]
                    _tabs[name] = {
                        "name": name,
                        "label": child.attrib["label"],
                        "toolnames": toolnames,
                    }
                    for elem in child:
                        if elem.tag != "memberTool":
                            continue
                        toolnames.append(elem.attrib["name"])
                elif child.tag == "shelfSet":
                    tabnames = []
                    name = child.attrib["name"]
                    _sets[name] = {
                        "name": name,
                        "label": child.attrib["label"],
                        "tabnames": tabnames,
                    }
                    for elem in child:
                        if elem.tag != "memberToolshelf":
                            continue
                        tabnames.append(elem.attrib["name"])

        self._sets = _sets
        self._tabs = _tabs
        self._tools = _tools
        self._cached = True
        # print("Read XML", time.time() - t)

    def _read_hom(self):
        if self._cached:
            return

        import time
        import hou
        from houdinihelp import api

        _sets = {}
        _tabs = {}
        _tools = {}

        # print("Reading from HOM...")
        t = time.time()
        for ssname, shelfset in hou.shelves.shelfSets().items():
            tabnames = []
            _sets[ssname] = {
                "name": ssname,
                "label": shelfset.label(),
                "tabnames": tabnames
            }
            for tabname, shelftab in shelfset.shelves():
                if tabname in _tabs:
                    continue
                toolnames = []
                _tabs[tabname] = {
                    "name": tabname,
                    "label": shelftab.label(),
                    "toolnames": toolnames
                }
                for toolname, tool in shelftab.tools():
                    if toolname in _tools:
                        continue
                    helpurl = tool.helpURL()
                    path = api.urlToPath(helpurl) if helpurl else None
                    _tools[toolname] = {
                        "name": toolname,
                        "label": tool.label(),
                        "icon": tool.icon().replace("_", "/", 1),
                        "help_url": helpurl,
                        "path": path,
                    }

        self._sets = _sets
        self._tabs = _tabs
        self._tools = _tools
        self._cached = True
        # print("Read HOM", time.time() - t)

    def apply(self, block, context, level=0, root=None):
        root = root or block
        for sub in block.get("body", ()):
            btype = sub.get("type")
            if btype in ("shelf_set", "shelf_tab", "shelf_tool"):
                # try:
                #     import hou
                # except ImportError:
                #     pages = context["pages"]
                #     self._read_xml(pages.store)
                # else:
                #     self._read_hom()
                pages = context["pages"]
                self._read_xml(pages.store)

                name = None
                attrs = sub.get("attrs")
                if attrs and "name" in attrs:
                    name = attrs["name"]
                elif "ext" in sub:
                    name = sub["ext"]
                    del sub["ext"]
                if not name:
                    continue

                sub["name"] = name
                if btype == "shelf_set":
                    set_data = self._sets.get(name)
                    if set_data:
                        self._shelf_set(root, sub, set_data, context,
                                        level=level + 1)
                elif btype == "shelf_tab":
                    tab_data = self._tabs.get(name)
                    if tab_data:
                        self._shelf_tab(root, sub, tab_data, context,
                                        level=level + 1)
                elif btype == "shelf_tool":
                    tool_data = self._tools.get(name)
                    if tool_data:
                        self._shelf_tool(root, sub, tool_data, context)

            elif sub.get("container"):
                d = int(sub.get("type") == "h" or
                        sub.get("role") in ("section", "heading"))
                self.apply(sub, context, level + d, root)

    def _shelf_set(self, rootblock, setblock, set_data, context, level=1):
        setblock["label"] = set_data.get("label")
        setblock["body"] = ssbody = []
        setblock["container"] = True

        for tabname in set_data["tabnames"]:
            tab_data = self._tabs.get(tabname)
            if tab_data:
                tabblock = {"type": "shelf_tab", "role": "heading",
                            "name": tabname}
                self._shelf_tab(rootblock, tabblock, tab_data, context,
                                level=level)
                ssbody.append(tabblock)

    def _shelf_tab(self, rootblock, tabblock, tab_data, context, level=1):
        tabblock["label"] = tab_data["label"]
        tabblock["level"] = level
        tabblock["container"] = True

        if not functions.string(tabblock.get("text")) and tabblock["label"]:
            tabblock["text"] = tabblock["label"]

        stbody = tabblock["body"] = []
        for toolname in tab_data["toolnames"]:
            tool_data = self._tools.get(toolname)
            if tool_data:
                tblock = {"type": "shelf_tool", "role": "item",
                          "name": toolname}
                self._shelf_tool(rootblock, tblock, self._tools[toolname],
                                 context)
                stbody.append(tblock)

    def _shelf_tool(self, rootblock, toolblock, tool_data, context):
        from bookish.wiki import includes

        toolblock.update(tool_data)
        toolpath = tool_data["path"]
        if not toolpath:
            return

        # print("name=", toolblock["name"])
        # print("path=", toolblock["path"])
        summary = None
        searcher = context.get("searcher")
        if searcher:
            fields = searcher.document(path=toolpath)
            if fields and "summary" in fields:
                summary = fields["summary"]
        # print("summary=", summary)

        pages = context["pages"]
        exists = pages.exists(toolpath)
        toolblock["exists"] = exists

        if not summary and exists:
            incl = includes.load_include_path(context["path"], toolpath,
                                              context, rootblock)
            if incl:
                sumblock = functions.first_subblock_of_type(incl, "summary")
                if sumblock:
                    summary = sumblock.get("text")

        toolblock["summary"] = summary


class VexPages(pipeline.Processor):
    name = "vex"
    before = ("groups",)
    after = ("hierarchy",)

    @staticmethod
    def _looks_like_an_arg(block):
        if block.get("type") == "dt":
            text = block.get("text", ())
            if isinstance(text, (list, tuple)) and len(text) == 1:
                item = text[0]
                return isinstance(item, dict) and item.get("type") == "code"

    @staticmethod
    def _process_context_page(block, context):
        # Find globals and make their name their IDs (to make
        # including easier)
        body = block.get("body", ())
        globalsect = functions.first_subblock_of_type(body, "globals_section")
        if globalsect:
            for sub in functions.find_items(globalsect, "globals_item"):
                attrs = sub.setdefault("attrs", {})
                if "id" not in attrs:
                    attrs["id"] = functions.string(sub.get("text", ""))

    @staticmethod
    def _process_function_page(block, context):
        # Automatically turn on "showtags" at the top level to show tag matches
        # in the "related" section on all VEX function pages
        attrs = block.setdefault("attrs", {})
        if "showtags" not in attrs:
            attrs["showtags"] = "true"

    @staticmethod
    def _process_arg(block):
        text = block.get("text", [])
        codespans = list(functions.find_spans_of_type(text, "code"))
        if not codespans:
            block["text"] = {"type": "code", "text": text}

    def apply(self, block, context):
        if block.get("type") == "root":
            # Only apply these changes to vex function pages
            if not context["path"].startswith("/vex/"):
                return

            attrs = block.get("attrs")
            if attrs:
                pagetype = attrs.get("type")
                if pagetype == "vexcontext":
                    self._process_context_page(block, context)
                elif pagetype == "vex":
                    self._process_function_page(block, context)

        for sub in block.get("body", ()):
            # if self._looks_like_an_arg(sub):
            #     sub["type"] = "arg"
            #     sub["role"] = "item"
            subtype = sub.get("type")
            if subtype == "arg":
                # Ensure an argument name is inside a "code" span
                self._process_arg(sub)
            elif subtype == "varg":
                # Change "varg" items to "arg" (so they group together) with a
                # special key
                sub["type"] = "arg"
                sub["variadic"] = True
            elif subtype == "returns":
                # Change "returns" items to "arg" (so they group together) with
                # a special key
                sub["type"] = "arg"
                sub["returns"] = True
            elif subtype in ("usage", "box") or sub.get("container"):
                # Recurse into containers
                self.apply(sub, context)


class HoudiniShortcuts(pipeline.TextModifier):
    """
    Implements Houdini-specific link features such as "opdef:" syntax and
    convenience schemes such as "Node:" and "Hom:".
    """

    name = "hshortcuts"
    before = ("promote", "includes", "joinkeys")

    do_properties = ("icon", "src")

    opdef_exp = re.compile("""
    opdef:
    /?  # Optional starting slash... not sure if Houdini supports this
    (?P<spec>[^?;]*)  # Node spec string
    ([?;](?P<section>.*))?  # Optional reference to a section inside the asset
    """, re.VERBOSE)

    def __init__(self, use_hou=True):
        self.use_hou = use_hou

    def _parse_opdef(self, currentpath, value):
        # Check that the value matches the opdef: regex
        match = HoudiniShortcuts.opdef_exp.match(value)
        if not match:
            return value

        spec = match.group("spec")
        # Supporting "." (meaning "current node") is easy, just tack the
        # section on to the current path
        if spec == ".":
            value = paths.basepath(currentpath) + "/" + match.group("section")
        elif self.use_hou:
            if "/" not in spec:
                return value

            # Because of the flawed design of namespaces/versions, it's
            # impossible to parse the names without asking Houdini. So,
            # suck it up and try to import hou
            try:
                import hou
                cffntn = hou.hda.componentsFromFullNodeTypeName
                # Use this unwieldy function to parse the name
                scopeop, namespace, nodetype, version = cffntn(spec)
                table, nodetype = nodetype.split("/", 1)
            except ImportError:
                # We can't import hou, so we can't support the fancy
                # scopes/namespaces/versions
                scopeop = None
                namespace = None
                table, nodetype = spec.split("/", 1)
                version = None
            nodetype = nodetype.replace("/", "_")

            # Convert the components into a server path
            from houdinihelp.api import components_to_path
            value = components_to_path(table, scopeop, namespace,
                                       nodetype, version)
            # Tack the section on the end
            section = match.group("section")
            if section:
                value += "/%s" % section

        return value

    def apply(self, block, context):
        path = context["path"]
        attrs = block.get("attrs")
        for name in self.do_properties:
            # This processor can run before "prop" blocks are converted into
            # attributes, so we have to deal with them
            if block.get("type") == "prop" and block["name"] == name:
                block["value"] = self._parse_opdef(path, block["value"])

            # Check for the name in top-level keys and in attrs
            if name in block:
                block[name] = self._parse_opdef(path, block[name])
            if attrs and name in attrs:
                attrs[name] = self._parse_opdef(path, attrs[name])

        # Find blocks including render properties and change them to includeprop
        # blocks
        btype = block.get("type")
        if btype == "include":
            ref = None
            if "ext" in block:
                ref = block["ext"]
            elif attrs and "ref" in attrs:
                ref = attrs["ref"]
            if ref and ref.startswith("/props/"):
                block["type"] = btype = "includeprop"

        # Find includeprop blocks and modify them so when included they look
        # like parameters
        if btype == "includeprop":
            ref = None
            if "ext" in block:
                ref = block["ext"]
            elif attrs and "ref" in attrs:
                ref = attrs["ref"]
            if ref:
                if "#" in ref:
                    pagename, propid = paths.split_fragment(ref)
                    propid = propid[1:]  # remove # from start of string
                else:
                    pagename = "mantra"
                    propid = ref

                if not pagename.startswith("/"):
                    pagename = "/props/" + pagename
                link = "%s#hprop=%s" % (pagename, propid)

                block["ref"] = link
                block["type"] = "include"
                block["newtype"] = "parameters_item"
                block["newid"] = propid

        if "text" in block:
            self.text(block["text"], context)

        body = block.get("body", ())
        for subblock in body:
            self.apply(subblock, context)

    def text(self, text, context):
        for span in text:
            # Only look at links
            if not (isinstance(span, dict) and span.get("type") == "link"):
                continue

            # The scheme is the "Node" in [Node:sop/copy]
            scheme = span.get("scheme")
            # The value is the "sop/copy" in [Node:sop/copy]
            value = span.get("value")

            # I hate this, but we have to support using Houdini-style "opdef:"
            # paths in help links to point to sections inside an asset
            if value.startswith("opdef:"):
                value = self._parse_opdef(context["path"], value)
                span["value"] = value

            # For certain shortcuts (e.g. HScript commands), copy the link
            # target to the fallback_text, we'll use it as the link text if the
            # fulltext index isn't available
            if scheme in ("Cmd", "Mantra"):
                span["fallback_text"] = value

            elif scheme in ("Exp", "Vex"):
                # For these schema, add empty parens to the fallback text to
                # indicate calls
                span["fallback_text"] = "%s()" % value

            if scheme == "IncludeProp":
                # This is a convenience to let node help authors include a
                # render property in the parameter documentation; convert it
                # into an include

                # Allow [IncludeProp:vm_blah] for mantra properties, and
                # [IncludeProp:opengl#ogl_diffuse] for properties in other files
                if "#" in value:
                    pagename, propid = paths.split_fragment(value)
                    propid = propid[1:]  # remove # from start of string
                else:
                    pagename = "mantra"
                    propid = value
                link = "/props/%s#hprop=%s" % (pagename, propid)

                span["type"] = "include"
                span["ref"] = link
                span["newtype"] = "parameters_item"
                span["newid"] = propid

            elif scheme == "Hom":
                value = value.replace(".", "/")
                span["value"] = "/hom/%s" % value
                if not span.get("text"):
                    fbtext = value.replace("/", ".").replace("#", ".")
                    span["fallback_text"] = fbtext

            elif scheme == "Key":
                from houdinihelp.hotkeys import hotkey_to_wiki, parse_key
                actionid = span.pop("value", None)
                span["keys_for"] = actionid
                keylist = None

                if self.use_hou:
                    try:
                        import hou
                    except ImportError:
                        pass
                    else:
                        if hasattr(hou, "hotkeys"):
                            keylist = hou.hotkeys.assignments(actionid)

                span["type"] = "keys"
                if keylist:
                    span["keys"] = keylist[0]
                    span["alt_keys"] = keylist[1:]
                else:
                    span["keys"] = parse_key(functions.string(span))

                del span["scheme"]
                del span["text"]

            elif scheme:
                # Call the "get_shortcut" function to use the scheme_map (above)
                # to deal with Houdini-specific link schemes such as "Node:" and
                # "Hom:"
                span["value"] = get_shortcut(scheme, value)

        return text


class ContentFroms(pipeline.Modifier):
    """
    Finds the "#contentfrom:" property and replaces it with an include.
    """

    name = "hcontentfrom"
    after = ("hierarchy",)
    before = ("properties", "includes")

    def modify(self, block, context):
        if block.get("type") == "prop" and block.get("name") == "contentfrom":
            ref = util.flatten_text(block.get("value")) + "/"
            del block["value"]
            block["type"] = "include"
            block["ref"] = ref


class HoudiniIds(pipeline.Processor):
    """
    Pre-processor for converting names of methods etc. into IDs.
    """

    name = "hids"

    @staticmethod
    def _method_id(text):
        bracket = text.find("(")
        return text[:bracket] if bracket >= 0 else text

    def apply(self, block, context):
        if block.get("type") != "root":
            return

        todo = [
            ("methods", self._method_id),
            ("functions", self._method_id),
            ("env_variables", functions.string),
            ("attributes", functions.slugify),
        ]

        fsot = functions.first_subblock_of_type
        for sectname, idfunc in todo:
            section = fsot(block, "%s_section" % sectname)
            if section:
                itemtype = "%s_item" % sectname
                for subblock in functions.find_items(section, itemtype):
                    if "id" in subblock:
                        continue

                    text = functions.string(subblock.get("text")).strip()
                    subblock["id"] = idfunc(text)


class HomTitles(pipeline.Processor):
    """
    Aesthetic processor that just takes the dotted prefix of a class/function
    name (e.g. hou.Node) and puts the part up to the last dot in the pre-title.
    """

    name = "homtitles"
    after = ("properties",)
    before = ("title",)

    def apply(self, block, context):
        attrs = block.get("attrs", {})
        if attrs.get("type") not in ("hommodule", "homclass", "homfunction"):
            return

        title = None
        tblock = functions.first_subblock_of_type(block, "title")
        if tblock:
            ttext = tblock.get("text")
            if ttext:
                title = functions.string(ttext).strip()

        # HOM titles should be the fully qualified name of the object. Take the
        # "prefix" (everything before the last dot) and put it in the page
        # supertitle
        if title:
            lastdot = title.rfind(".")
            if lastdot >= 0:
                tblock["text"] = [
                    {"type": "supertitle", "text": title[:lastdot + 1]},
                    title[lastdot + 1:],
                ]

            # Copy the page title in an attribute on any value items, so
            # even if they're imported somewhere else they can recall their
            # fully-qualified name
            section = functions.first_subblock_of_type(block, "values_section")
            if section:
                for item in functions.find_items(section):
                    item["prefix"] = title


class HomClasses(pipeline.Processor):
    """
    Post-processor for several features related to HOM pages, such as listing
    subclasses and methods inherited from superclasses.
    """

    name = "homclasses"
    before = ("annotate",)

    def _annotate_subclasses(self, searcher, path, block):
        fqname = path[5:].replace("/", ".")
        subclasses = []
        for subdoc in searcher.documents(superclass=fqname):
            subclasses.append({
                "title": subdoc.get("title"),
                "path": subdoc.get("path"),
                "summary": subdoc.get("summary")
            })
        subclasses.sort(key=lambda d: d["title"])
        block["subclasses"] = subclasses

    def _get_method_names(self, block):
        methodnames = set()
        section = functions.subblock_by_id(block, "methods")
        if section:
            for methblock in functions.find_items(section, "methods_item"):
                text = functions.string(methblock.get("text"))
                bracket = text.find("(")
                name = text[:bracket] if bracket >= 0 else text
                methodnames.add(name)
        return methodnames

    def _superclasses(self, pages, methodnames, context, block, history=None):
        # Recursively loads the doc pointed to by the block's "superclass"
        # attribute and yields a (path, rootblock) pair for each superclass

        history = history or set()
        attrs = block.get("attrs", {})
        superclass = attrs.get("superclass")
        if superclass:
            # TODO: This will need to be language-aware
            path = "/hom/" + superclass.replace(".", "/")
            spath = pages.source_path(path)

            if pages.exists(spath):
                if spath in history:
                    raise Exception("Circular superclass structure")
                else:
                    history.add(spath)

                doc = pages.json(spath, context, postprocess=False)

                titleblock = functions.first_subblock_of_type(doc, "title")
                if titleblock:
                    title = functions.string(titleblock.get("text"))
                else:
                    title = superclass

                # Find the method items on the superclass
                section = functions.subblock_by_id(doc, "methods")
                methods = []
                if section:
                    for methblock in functions.find_items(doc, "methods_item"):
                        text = methblock.get("text")
                        name = functions.string(text).split("(")[0]

                        # If this name is in the set of seen methods, it's
                        # overridden, so we should skip it
                        if name in methodnames:
                            continue
                        methodnames.add(name)
                        methods.append(methblock)

                yield path, title, methods
                for x in self._superclasses(pages, methodnames, context, doc,
                                            history):
                    yield x

    def apply(self, block, context):
        # Only operate on HOM class documents
        attrs = block.get("attrs", {})
        if attrs.get("type") != "homclass":
            return

        path = paths.basepath(context["path"])
        pages = context["pages"]
        searcher = context["searcher"]

        # Find the subclasses using the full-text index
        if searcher:
            self._annotate_subclasses(searcher, path, block)

        # Get a list of methods on this class, so we can check if one of
        # the super methods is overridden
        methodnames = self._get_method_names(block)

        # Recursively include the docs for superclass methods

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

        # Get a list of (path, title, list_of_method_blocks) tuples
        supers = list(self._superclasses(pages, methodnames, context, block))
        # The list is in order from immediate superclass to furthest ancestor;
        # for display, add the headings in reverse order
        for path, title, supmethods in reversed(supers):
            # Don't create a heading if there aren't any methods on this class
            if not supmethods:
                continue

            # Generate the heading text
            # TODO: how to translate this?
            text = [
                "Methods from ",
                {"type": "link", "value": path, "text": title}
            ]

            # Attributes for the generated heading: don't index the contents
            # (they're indexed on their original page), add a glyph to make it
            # clearer these are superclass methods
            attrs = {"index": "no", "glyph": "fa-angle-double-up"}

            # Generate the heading block to hold the method blocks
            heading = {"type": "h", "text": text, "attrs": attrs,
                       "container": True, "role": "heading", "body": supmethods,
                       "level": 2,
                       "super_path": path, "super_title": title,
                       }
            methodsbody.append(heading)

        block["superclasses"] = [
            {"path": path, "title": title}
            for path, title, _ in supers
        ]


class Itemize(pipeline.Processor):
    name = "itemize"
    after = ("properties", "sections", "includes", "sortheadings")
    before = ("groups",)

    sections = ("parameters", "attributes")

    def apply(self, block, context):
        for name in self.sections:
            sectname = "%s_section" % name
            section = functions.first_subblock_of_type(block, sectname)
            if section:
                self._itemize(section, name)

    def _itemize(self, block, name):
        bt = block.get("type", "")

        if bt == "dt":
            block["type"] = "%s_item" % name
            block["role"] = "item"

        elif bt == "dt_group":
            block["type"] = "%s_item_group" % name
            for subblock in block.get("body", ()):
                self._itemize(subblock, name)

        elif bt.endswith("_item_group") or block.get("role") == "item":
            return

        elif block.get("container"):
            for subblock in block.get("body", ()):
                self._itemize(subblock, name)


class ExampleFiles(pipeline.Processor):
    """
    For example files, computes the nodes and example files and adds them as
    annotations on the document.

    For node docs, searches for examples related to the node.

    For everything else, looks for example loader markup.
    """

    name = "hexamples"
    before = ("includes",)

    def apply(self, block, context):
        # At the document root
        if block.get("type") == "root":
            attrs = block.get("attrs", {})
            path = context["path"]
            dirpath, filename = paths.split_dirpath(path)
            basename, ext = paths.split_extension(filename)

            # Is this an example documentation file?
            is_node_eg = (path.startswith("/examples/nodes/") and
                          not basename.startswith("_") and
                          not basename == "index")
            is_panel_eg = (path.startswith("/examples/python_panels/") and
                           not basename.startswith("_") and
                           not basename == "index")

            if is_node_eg or is_panel_eg:
                # This is an example doc
                self._process_example_page(block, context, is_node_eg,
                                           is_panel_eg)

    def _process_example_page(self, root, context, is_node_eg, is_panel_eg):
        # Processes an example doc page
        path = context["path"]
        attrs = root.get("attrs", {})

        # Example authors are very lax about giving the example documents
        # titles; if the document doesn't have a title, make one up from the
        # file name
        title = functions.first_subblock_of_type(root, "title")
        if not title:
            name = paths.barename(path)
            body = root.setdefault("body", [])
            body.insert(0, {
                "type": "title", "indent": 0, "text": [name]
            })

        # Check for an explicit exampleFor property, otherwise guess it
        # from the example's directory tree
        if is_node_eg:
            root.setdefault("attrs", {})["type"] = "example"

            if "exampleFor" in attrs:
                egfor = attrs["exampleFor"]
            elif "examplefor" in attrs:
                egfor = attrs["examplefor"]
            else:
                egfor = self._node_path_from_example_path(path)
            # Attach the list of nodes to the root
            root["examplefor"] = egfor

        egpath = None
        # Check for an explicit exampleFile property, otherwise guess it
        # by looking for the example name with an extension
        if "exampleFile" in attrs:
            egpath = attrs["exampleFile"]
        elif "examplefile" in attrs:
            egpath = attrs["examplefile"]
        elif is_node_eg:
            base = paths.basepath(path)
            for ext in (".hda", ".otl"):
                egpath = base + ext
                if context["pages"].exists(egpath):
                    break
        elif is_panel_eg:
            egpath = self._file_path_from_panel_path(path)

        # print("path=", path, "egpath=", egpath)

        if egpath:
            egpath = paths.join(path, egpath)
            if context["pages"].exists(egpath):
                root["examplefile"] = egpath

    # @staticmethod
    # def _example_items(pages, egdocs, context, include=False):
    #     items = []
    #     for egdoc in egdocs:
    #         data = {"type": "load_example"}
    #         if include:
    #             egdata = pages.json(egdoc["path"],
    #                                 context.push({"including": True}))
    #             if egdata:
    #                 body = egdata.get("body", ())
    #                 attrs = egdata.get("attrs", {})
    #                 title = functions.first_subblock_of_type(body, "title")
    #                 summary = functions.first_subblock_of_type(body, "summary")
    #
    #                 data["body"] = functions.remove_subblocks(body, ("title",))
    #                 data["examplefile"] = attrs.get("examplefile")
    #                 data["examplefor"] = attrs.get("examplefor")
    #
    #                 if title:
    #                     data["text"] = title.get("text", ())
    #                 if summary:
    #                     data["summary"] = summary.get("text", ())
    #
    #         if not data.get("text"):
    #             data["text"] = egdoc.get("title")
    #         if not data.get("summary") and "summary" in egdoc:
    #             data["summary"] = egdoc["summary"]
    #         if not data.get("examplefile"):
    #             data["examplefile"] = egdoc.get("examplefile")
    #         if not data.get("examplefor"):
    #             data["examplefor"] = egdoc.get("examplefor")
    #         data["path"] = egdoc["path"]
    #         items.append(data)
    #
    #     items.sort(key=lambda d: d.get("text", ""))
    #     return items

    @staticmethod
    def _node_path_from_example_path(path):
        # Guess the node based on what directory the example is in
        parts = paths.norm_parts(path)
        # Remove the examples prefix
        assert parts.pop(1) == "examples/"
        # Remove the filename from the end
        parts.pop()
        # Put the path back together
        nodepath = "".join(parts)
        if nodepath.endswith("/"):
            nodepath = nodepath[:-1]
        return nodepath

    @staticmethod
    def _file_path_from_panel_path(path):
        return paths.basepath(path) + ".pypanel"


class NodeMetadata(pipeline.Processor):
    """
    Uses HOM to attach additional metadata to node docs after they're parsed.
    """

    name = "nodemetadata"

    def __init__(self, use_hou=True):
        self.use_hou = use_hou

    def apply(self, block, context):
        if not self.use_hou:
            return
        try:
            import hou
        except ImportError:
            return

        path = paths.basepath(context["path"])
        dpath = langpaths.safe_delang(path)
        if not dpath.startswith("/nodes/"):
            return

        # If we're allowed to use HOM, use it to get additional metadata
        from houdinihelp.api import path_to_nodetype, nodetype_to_path
        nodetype = path_to_nodetype(dpath)
        if nodetype and nodetype.hidden():
            block["node_hidden"] = True
        if nodetype and nodetype.deprecated():
            block["node_deprecated"] = True
            info = nodetype.deprecationInfo()
            if "new_type" in info:
                new_type = info["new_type"]
                if new_type:
                    # Using snap_version here may or may not trigger Flask's
                    # stupid AppContext nonsense
                    new_path = nodetype_to_path(new_type, snap_version=True,
                                                pages=context["pages"])
                    new_path += ".html"
                    block["node_replacement_type"] = new_type
                    block["node_replacement_path"] = new_path
                    block["node_replacement_label"] = new_type.description()

            if "reason" in info:
                block["node_deprecation_reason"] = info["reason"]
            if "version" in info:
                block["node_deprecation_version"] = info["version"]

        body = block.get("body", ())
        oldtitle = functions.first_subblock_of_type(body, "title")
        if oldtitle is None and nodetype:
            # Get the node label from HOM
            newtitle = nodetype.description()
            if newtitle:
                # Create a fake title block and add it to the beginning of
                # the document body
                tblock = {"type": "title", "text": [newtitle]}
                body.insert(0, tblock)


class ExampleSearches(pipeline.Processor):
    def apply(self, block, context, root=None):
        root = root or block

        attrs = block.get("attrs", {})
        if block.get("type") == "root" and attrs.get("type") == "node":
            # This is a node doc, add associated examples
            self._process_node_page(block, context)

        # No point looking for example listers if we don't have a searcher
        if not context.get("searcher"):
            return

        # Look for :load_example: items
        blocktype = block.get("type")
        body = block.get("body")
        if blocktype == "load_example":
            self._process_load_block(block, context, root)
        elif blocktype == "list_examples":
            self._process_list_block(block, context, root)
        elif body:
            for sub in body:
                self.apply(sub, context, root)

    def _process_node_page(self, root, context):
        # Processes a node doc page: add references to examples and usages

        path = context["path"]
        pages = context["pages"]
        searcher = context["searcher"]
        if not searcher:
            return
        body = root.setdefault("body", [])

        # Find direct examples
        pagelang = pages.page_lang(path)
        vpath = paths.basepath(path)
        egdocs = list(searcher.documents(examplefor=vpath, lang=pagelang))
        if egdocs:
            egblock = self._get_or_add_eg_block(body)
            # Convert them to blocks and add them to the examples section
            egblock["body"].extend(self._hits_to_blocks(egdocs, context, root))

        # Find usages
        usagedocs = list(searcher.documents(uses=vpath))
        if usagedocs:
            egblock = self._get_or_add_eg_block(body)
            # Put them in an attribute on the examples section
            egblock["usages"] = list(
                self._hits_to_blocks(usagedocs, context, root)
            )

    @staticmethod
    def _get_or_add_eg_block(body):
        egblock = functions.first_subblock_of_type(body, "examples_section")

        if not egblock:
            # This page doesn't have an examples section, we have to
            # make one
            egblock = {
                "type": "examples_section", "role": "section",
                "id": "examples", "level": 1, "container": True,
                "text": "Examples", "body": [],
            }
            body.append(egblock)

        if "body" not in egblock:
            egblock["body"] = []

        return egblock

    @classmethod
    def _process_list_block(cls, block, context, root):
        # Processes a :list_examples: block... runs the search, turns the
        # results into loader blocks, and puts them in the block body
        searcher = context.get("searcher")
        if not searcher:
            return

        # TODO: search should be made language-aware, but that would break the
        # current English docs that are not under +en.
        r = pipeline.RunSearches.get_results(block, context)
        attrs = block.get("attrs", {})
        body = block.setdefault("body", [])

        if not r.is_empty():
            if "groupedby" in attrs:
                for key, docnums in sorted(r.groups().items()):
                    hits = searcher.group_hits(docnums)

                    # The type must not end in _group, because there's a step in
                    # the pipeline that coalesces adjacent groups of the same
                    # type
                    body.append({
                        "type": "grouped_examples", "key": key,
                        "body": list(cls._hits_to_blocks(hits, context, root)),
                        "container": True,
                    })
            else:
                body.extend(cls._hits_to_blocks(r, context, root))

    @classmethod
    def _hits_to_blocks(cls, hits, context, root):
        # Transforms search hits into loader blocks
        for hit in hits:
            if paths.basename(hit["path"]) != "index":
                yield cls.make_load_example(hit, context, root)

    @staticmethod
    def make_load_example(hit, context, root):
        # Creates a loader block based on a search hit
        from bookish.wiki import includes

        egpath = hit["path"]
        body = includes.load_include_path(
            context["path"], egpath, context, root
        )
        if body is None:
            body = []

        return {
            "type": "load_example",
            "attrs": {
                "path": egpath,
                "examplefile": hit.get("examplefile"),
                "examplefor": hit.get("examplefor"),
            },
            "text": hit.get("title", egpath),
            "body": body
        }

    @classmethod
    def _process_load_block(cls, block, context, root):
        # Processes a :load_example: block... loads the referenced example page
        # and copies page metadata onto the block
        searcher = context.get("searcher")
        if not searcher:
            return

        attrs = block.setdefault("attrs", {})
        egpath = attrs.get("path")
        egfile = attrs.get("examplefile")
        title = functions.string(block.get("text"))
        if egpath:
            fields = searcher.document(path=egpath)
            if fields:
                if not egfile:
                    attrs["examplefile"] = fields.get("examplefile")
                if not title:
                    block["text"] = fields.get("title")

            if attrs.get("include") == "yes":
                from bookish.wiki import includes
                block["body"] = includes.load_include_path(
                    context["path"], egpath, context, root
                )


class RewriteReplaces(pipeline.Processor):
    """
    A long time ago, instead of putting /commands/ophide as the path in a
    replaces property, someone wrote Cmd:ophide somehow assuming that would
    work. I should really go back and just replace them all, but rewriting
    them at runtime isn't so bad, and who knows who might try the same thing
    again someday, so I might as well make it work.

    Also, someone else decided they wanted that instead of using a page
    property, they wanted to write a @replaces section with links inside, so
    I have to support that too. This processor looks for such a section and
    translates it into a page property.

    This has to run as a preprocessor (so the results are visible to the
    indexer, which currently skips postprocessing), so it's split from the
    "Replacments" post-processor which does the reverse lookup on "replaced"
    pages.
    """

    name = "hreplaces"
    split_expr = re.compile("[ ,]+")
    fields = ("title", "path", "type", "summary", "icon")

    @staticmethod
    def _do(block):
        attrs = block["attrs"]
        text = attrs["replaces"]
        # Split the space/comma separated string
        replacelist = RewriteReplaces.split_expr.split(text)
        if replacelist:
            replaces = []
            for path in replacelist:
                replaces.append(parse_shortcut(path))
            attrs["replaces"] = " ".join(replaces)

    def apply(self, block, context, root=None, in_replaces=False):
        # Find #replaces: properties and parses any Cmd:foo or Exp:bar
        # type strings into actual paths

        if root is None:
            root = block
        attrs = block.get("attrs", {})

        # If this block has a "replaces" property, rewrite it
        if "replaces" in attrs:
            self._do(block)

        # Look for a "replaces" section
        if block.get("role") == "section" and block.get("id") == "replaces":
            in_replaces = True
        elif in_replaces:
            # If we're in a @replaces section, look for any links
            for span in block.get("text", ()):
                if isinstance(span, dict) and span.get("type") == "link":
                    rpath = span.get("fullpath")
                    if rpath:
                        rpath = parse_shortcut(rpath)
                        if "replaces" in root:
                            root["replaces"] += " " + rpath
                        else:
                            root["replaces"] = rpath

        # Recurse inside this block
        for subblock in block.get("body", ()):
            self.apply(subblock, context, root, in_replaces)


class Replacements(pipeline.Processor):
    """
    If a searcher is available, this processor finds any documents that
    "replace" the current path, and adds information about them to a
    "replacedby" list on the document root, making them available to display
    in the document. This is to support linking from HScript commands to the
    replacement HOM equivalents.
    """

    name = "hreplacements"
    prefixes = ("/commands/", "/expressions/", "/nodes/")
    fields = ("title", "path", "type", "summary", "icon")

    def apply(self, block, context):
        # Find any documents that replace this one

        # Abort if we don't have a searcher
        searcher = context.get("searcher")
        if not searcher:
            return

        path = paths.basepath(context["path"])
        # print("path=", path)
        # Only run the search for pages the start with one of the
        # prefixes listed in the class's prefixes attribute
        for prefix in self.prefixes:
            # print("prefix=", prefix, path.startswith(prefix))
            if path.startswith(prefix):
                repls = []
                # Look for documents with this page's path in their
                # "replaces" field
                # print("docs=", list(searcher.documents(replaces=path)))
                for doc in searcher.documents(replaces=path):
                    d = dict((f, doc[f]) for f in self.fields if f in doc)
                    repls.append(d)
                if repls:
                    # Put the replacement documents in a "replacedby"
                    # key on this page's root
                    block["replacedby"] = repls
                return


class Actions(pipeline.Processor):
    name = "hactions"
    before = ("groups",)

    def __init__(self, use_hou=True):
        self.use_hou = use_hou

    def apply(self, block, context, action_context=''):
        attrs = block.get("attrs", {})
        blocktype = block.get("type")
        body = block.get("body", ())
        descend = True

        # Temporarily hide @actions sections from display, until we have the
        # hotkey functions necessary to make them worthwhile
        if block.get("type") == "root":
            actions = functions.first_of_type(block, "actions_section")
            if actions:
                actions_attrs = actions.setdefault("attrs", {})
                actions_attrs["status"] = "hidden"

        # Any block type can have an #action_context: property that sets the
        # hotkey context for its descendant blocks
        if "action_context" in attrs:
            action_context = attrs.get("action_context", "")

        # Rename actions_item blocks to just "action"
        if blocktype == "actions_item":
            blocktype = block["type"] = "action"

        # If an "action" item has an #id: property, use it as a shorthand to
        # generate an action attribute
        if blocktype == "action":
            blockid = attrs.get("id")
            if blockid:
                attrs["action"] = blockid
                del attrs["id"]
            # Don't bother recursing inside action items
            descend = False

        # Any block type can have an #action: property that sets this block
        # as the documentation for a hotkey action
        if "action" in attrs:
            action_id = attrs["action"]

            if action_id.startswith("."):
                # If the action ID starts with a dot, assume it's meant to be
                # concatenated with the current action context
                action_id = "%s%s" % (action_context, action_id)
                attrs["action"] = action_id
            elif "." not in action_id:
                # If the action ID does not have a dot in it, assume it's meant
                # to be concatenated with the current action context
                action_id = "%s.%s" % (action_context, action_id)
                attrs["action"] = action_id

            # Use HOM to get the hotkey current associated with this action
            if action_id and self.use_hou:
                keys = None
                try:
                    import hou
                    if hasattr(hou, "ui"):
                        try:
                            keys = hou.ui.hotkeys(action_id)
                        except ValueError:
                            # Try to get word out that the Houdini didn't find
                            # the action ID
                            block["action_id_error"] = action_id
                except ImportError:
                    pass

                if not keys and "hotkeys" in attrs:
                    # Fall back on manually-listed hotkeys if they exist
                    keys = [s.strip() for s in attrs["hotkeys"].split(",")]

                if keys:
                    from houdinihelp.hotkeys import hotkey_to_wiki
                    block["hotkeys"] = [hotkey_to_wiki(k) for k in keys]

        if not descend:
            return

        # if "text" in block:
        #     text = block["text"]
        #     if isinstance(text, list):
        #         block["text"] = self._process_text(text)

        # Recurse into sub-blocks
        for subblock in body:
            self.apply(subblock, context, action_context=action_context)

    # def _process_text(self, text):
    #     from houdinihelp import hotkeys
    #     try:
    #         import hou.ui
    #     except ImportError:
    #         hou = None
    #
    #     i = 1
    #     while i < len(text):
    #         if isinstance(text[i], dict) and text[i].get("type") == "keys":
    #             ks = text[i]["keys"]
    #             for i, k in enumerate(ks):
    #                 if k.startswith("!") and hou:
    #                     hkeys = [hotkeys.hotkey_to_wiki(hk) for hk
    #                              in hou.ui.hotkeys(k[1:])]
    #
    #
    #
    #             # Coalesce consecutive key spans
    #             if isinstance(text[i - 1], dict) and text[i - 1].get("type") == "keys":
    #                 text[i - 1]["keys"].extend(text.pop(i)["keys"])
    #                 continue
    #         i += 1


class Suites(pipeline.Processor):
    name = "suites"

    retain = {
        "vexsuite": ["summary", "usage_group", "arg_group", "usage", "arg"]
    }

    def apply(self, block, context):
        # This only runs at the root leve, and finds the "suite" section. A
        # helper function then recurses on its body, and this function
        # replaces the section with the processed body.

        body = block.get("body", ())
        # We have to count by index here so we can modify the list in-place
        i = 0
        while i < len(body):
            subblock = body[i]
            if subblock.get("type") == "suite_section":
                suitebody = subblock.get("body")
                self._process(context, block, subblock)
                # Replace the section with its own contents
                body[i:i + 1] = suitebody
                i += len(suitebody)
            else:
                i += 1

    def _process(self, context, root, block):
        body = block.get("body", ())
        i = 0
        while i < len(body):
            subblock = body[i]
            sbtype = subblock.get("type")

            if sbtype == "suite_list":
                self._suite_list(context, root, subblock)
            if sbtype == "suite_item":
                self._suite_item(context, root, subblock)

            # Recurse on containers
            if subblock.get("container"):
                self._process(context, root, subblock)

            i += 1

    def _suite_list(self, context, root, block):
        attrs = block.get("attrs", {})
        if "sortedby" not in attrs:
            attrs["sortedby"] = "title"

        r = pipeline.RunSearches.get_results(block, context)
        if not r or r.is_empty():
            return

        body = block.setdefault("body", [])

        for hit in r:
            item = dict(type="suite_item", body=[], fields=hit.fields())
            self._include_contents(context, root, item, hit["path"])
            body.append(item)

    def _suite_item(self, context, root, block):
        # Find the link in the block's text
        link = functions.first_span_of_type(block.get("text", ()), "link")
        if not link:
            return
        refpath = link.get("fullpath")
        if not refpath:
            return

        self._include_contents(context, root, block, refpath)

    def _include_contents(self, context, root, block, refpath):
        from bookish.wiki import includes

        # Use the include machinery to get the referenced page's contents and
        # add it to this block's contents
        pagetype = functions.attr(root, "type")
        iblock = includes.make_include(refpath,
                                       retain=self.retain.get(pagetype))
        body = block.setdefault("body", [])
        included = includes.get_included(iblock, context, root)
        body.extend(included)

        # If the block doesn't already have an ID, set it based on the included
        # page
        if not functions.topattr(block, "id"):
            attrs = block.setdefault("attrs", {})
            attrs["id"] = paths.basename(refpath)


class IconAliases(pipeline.Processor):
    # This processor looks for references to icons and rewrites them according
    # to the IconMapping file. This used to be done much more robustly and
    # efficiently at the VFS level, where it didn't matter how an icon was
    # requested, we just redirected the file access. However, now that the new
    # underlying web server serves static files itself (for a huge speed boost),
    # the help server code never sees the icon request, so we have to do it this
    # way, problematically trying to find all the different ways the system
    # allows the author to specify an icon and rewrite each way. I will try to
    # think of a way to make this cleaner and more consistent in the future.

    name = "iconaliases"
    after = ("annotate",)

    line_expr = re.compile("""
    ^  # definition must start in first column (no indents!)
    (?P<ddir>[A-Za-z0-9]*)_(?P<dname>[^ \t:]+)  # "destination" dir and name
    [ \t]*:=[ \t]*  # Assignment "operator", with optional whitespace
    (?P<sdir>[A-Za-z0-9]*)_(?P<sname>[^; \t\n]+)  # "source" dir and name
    [ \t]*;?$  # Line should end with a semicolon
    """, re.VERBOSE)

    path_expr = re.compile("^(?P<dir>[^/]+)/(?P<name>[^/]+)$")

    def _read_alias_file(self, context):
        pages = context["pages"]
        store = pages.store

        mapping_path = "/icon_config/IconMapping"
        line_exp = self.line_expr
        mappings = {}

        if store.exists(mapping_path):
            with store.open(mapping_path) as f:
                lines = f.read().decode("utf-8")
                for line in lines.split("\n"):
                    m = line_exp.match(line)
                    if m:
                        sdir = m.group("sdir")
                        sname = m.group("sname")
                        ddir = m.group("ddir")
                        dname = m.group("dname")
                        mappings[ddir, dname] = sdir, sname

        return mappings

    def _cache(self, context):
        cache = context.get("icon_alias_cache")
        if cache is None:
            cache = self._read_alias_file(context)
            context["icon_alias_cache"] = cache
        return cache

    def _rewrite(self, path, context):
        cache = self._cache(context)
        m = self.path_expr.match(path)
        if m:
            key = m.group("dir"), m.group("name")
            if key in cache:
                path = "%s/%s" % cache[key]
        return path

    def apply(self, block, context):
        btype = block.get("type")
        attrs = block.get("attrs", {})

        if "icon" in attrs:
            attrs["icon"] = self._rewrite(attrs["icon"], context)

        if "fields" in attrs:
            fields = attrs["fields"]
            if "icon" in fields:
                fields["icon"] = self._rewrite(fields["icon"], context)

        if btype == "list":
            for hit in block.get("hits", ()):
                if "icon" in hit:
                    hit["icon"] = self._rewrite(hit["icon"], context)

        # It's really bad that I have to hard-code the stupid pseudo-schemes
        # "Largeicon" and "Smallicon" here, but I've painted myself into a
        # corner
        if btype == "link" and block.get("scheme") in ("Icon", "Largeicon",
                                                       "Smallicon"):
            block["value"] = self._rewrite(block["value"], context)

        text = block.get("text")
        if text:
            for span in block["text"]:
                if isinstance(span, dict):
                    self.apply(span, context)

        for subblock in block.get("body", ()):
            self.apply(subblock, context)

    def process_indexed(self, pages, block, doc, cache):
        icon = doc.get("icon")
        if icon:
            ctx = pages.wiki_context(doc["path"])
            doc["icon"] = self._rewrite(icon, ctx)

