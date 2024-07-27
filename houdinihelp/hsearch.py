import copy
import re
import sys

from whoosh import fields, columns

from bookish import paths, util, functions
from bookish.search import default_fields, Searchables


# All VEX contexts

vexcontexts = "surface displace light shadow fog chop pop sop cop2 image3d cvex"


class DoNotIndex(Exception):
    pass


# Helper functions

def find_parms(block):
    """
    Recursively finds dt blocks inside containers (but doesn't recurse inside
    the dt blocks). This is necessary because for bad historical reasons nodes
    docs don't mark parameters as items like they should.
    """

    if block.get("type") in ("dt", "parameter"):
        yield block
    elif block.get("container"):
        body = block.get("body", ())
        for subblock in body:
            for x in find_parms(subblock):
                yield x


ws_exp = re.compile("[\t\r\n ]+")


dir_to_subject = {
    "anim": "Animation",
    "assets": "Assets",
    "basics": "Basics",
    "character": "Character",
    "chop": "CHOPs",
    "cloth": "Cloth",
    "commands": "HScript",
    "composite": "Compositing",
    "copy": "Copying/Instancing",
    "crowds": "Crowds",
    "dopparticles": "Particles",
    "dyno": "Dynamics",
    "expressions": "Expressions",
    "fluid": "Fluids",
    "fur": "Hair and Fur",
    "grains": "Grains",
    "help": "About Help",
    "hom": "Scripting",
    "io": "Import/Export",
    "model": "Geometry",
    "mplay": "MPlay",
    "network": "Network/Parms",
    "news": "What's New",
    "props": "Render Properties",
    "pypanel": "Python Panels",
    "pyro": "Pyrotechnics",
    "ref": "Reference",
    "render": "Rendering",
    "shade": "Shading",
    "shelf": "Shelf tools",
    "start": "Starting",
    "vex": "VEX",
    "visualizers": "Visualizers",
}


houdini_fields = {
    "instant": fields.KEYWORD(commas=False, lowercase=True),
    "instant_doc": fields.STORED,
    "status": fields.ID(stored=True),
    "superclass": fields.ID(stored=True),
    "replaces": fields.KEYWORD(stored=True),
    "version": fields.ID,
    "summary": fields.STORED,
    "helpid": fields.KEYWORD,
    "context": fields.KEYWORD(commas=False, stored=True),
    "namespace": fields.KEYWORD(commas=True, stored=True),
    "examplefile": fields.STORED,
    "examplefor": fields.KEYWORD(stored=True),
    "uses": fields.KEYWORD,
    "group": fields.ID(sortable=columns.RefBytesColumn(), stored=True),
    "library_path": fields.ID,
}


class HoudiniSearchables(Searchables):
    @staticmethod
    def _attr(attrs, name):
        return attrs.get(name) or None

    def schema(self):
        schema = super(HoudiniSearchables, self).schema()
        for fieldname, fieldtype in houdini_fields.items():
            schema.add(fieldname, fieldtype)
        return schema

    def _should_index_block(self, block):
        attrs = block.get("attrs")
        status = attrs.get("status") if attrs else None
        if status == "ni":
            return False

        return super(HoudiniSearchables, self)._should_index_block(block)

    def _should_index_document(self, pages, path, root, block):
        from houdinihelp.api import (nodetype_to_path, path_to_components,
                                     path_to_nodetype)

        # Hide nodes that are hidden or superceded
        # Only do this test at the top level (not for every sub-doc)
        if pages.use_hou and path.startswith("/nodes/") and block is root:
            # See if we can turn the path into a nodetype using HOM
            nodetype = path_to_nodetype(path)
            if nodetype:
                if nodetype.hidden() or nodetype.deprecated():
                    return False

                comps = path_to_components(path)
                # Check if the node has been superseded by a more recent version
                order = nodetype.namespaceOrder()
                if order and nodetype.name() != order[0]:
                    return False
                elif order and comps.version is None:
                    # Check for a situation where the user has named their help
                    # files incorrectly and there is both an *unversioned* file
                    # (e.g. bar.txt) *and* an explicit file for the latest
                    # version (e.g. bar-5.0.txt). In this case, ignore the
                    # unversioned file. Otherwise you'll have two documents in
                    # the index that claim to document the same node.
                    latest_type = nodetype.category().nodeType(order[0])
                    if latest_type:
                        lt_path = nodetype_to_path(latest_type)
                        lt_spath = pages.source_path(lt_path)
                        if pages.exists(lt_spath):
                            # print("Redundant page:", path, "->", lt_spath)
                            return False

        rootattrs = root.get("attrs")
        pagetype = rootattrs.get("type") if rootattrs else None
        attrs = block.get("attrs")
        blocktype = block.get("type")

        if attrs and attrs.get("status") == "ni":
            return False

        # Recognize Houdini-specific sub-documents
        if (
            (blocktype == "env_variables_item" and pagetype == "env") or
            (blocktype == "methods_item" and pagetype == "homclass") or
            (blocktype == "functions_item" and pagetype == "hommodule") or
            (blocktype == "properties_item" and pagetype == "properties")
        ):
            return True
        else:
            return super(HoudiniSearchables, self)._should_index_document(
                pages, path, root, block
            )

    def _make_doc(self, pages, path, root, block, text, cache):
        doc = super(HoudiniSearchables, self)._make_doc(pages, path, root,
                                                        block, text, cache)

        blocktype = block.get("type")

        if blocktype in ("methods_item", "functions_item"):
            self._process_method(pages, path, root, block, doc)
        elif blocktype == "properties_item":
            self._process_property(pages, path, root, block, doc)
        elif blocktype == "attributes_item":
            self._process_attribute(pages, path, root, block, doc)
        elif blocktype == "env_variables_item":
            self._process_env_variable(pages, path, root, block, doc)
        else:
            self._process_doc(pages, path, root, block, doc)

        return doc

    @staticmethod
    def _add_instant(doc, doctype, attrs, block):
        # Compute the keywords (if any) that will trigger showing this doc as
        # an "instant answer" at the top of the search results
        instants = []
        if "instant" in attrs:
            instants.append(attrs["instant"])

        if doctype == "node" and "internal" in attrs:
            instants.append(attrs["internal"])

        if doctype in ("vex", "vexstatement", "hscript", "expression"):
            instants.append(doc.get("title", ""))

        if doctype in ("hommodule", "homfunction", "homclass", "hommethod"):
            name = doc.get("title", "")
            if name:
                if "." in name:
                    name = name[name.rfind(".") + 1:]
                if "(" in name:
                    name = name[:name.find("(")]
                instants.append(name)

        if doctype == "property" and "hprop" in attrs:
            instants.append(attrs["hprop"])

        if instants:
            doc["instant"] = ",".join(instants)

        # Compute the contents of the "instant answer" document to show at the
        # top of the results
        body = []
        summblock = functions.first_subblock_of_type(block, "summary")

        if doctype in ("vex", "hscript", "homfunction", "command",
                       "expression"):
            body.append(summblock)
            usages = []
            for sub in functions.find_all_depth(block):
                if sub.get("type") == "usage":
                    sub = sub.copy()
                    sub["body"] = ()
                    usages.append({"type": "usage_group", "body": sub})
            body.extend(usages)

        elif doctype == "node":
            body.append(summblock)

        elif doctype == "vexstatement":
            body.append(summblock)
            preblock = functions.first_of_type(block, "pre")
            if preblock:
                body.append(preblock)

        elif doctype == "homclass":
            body.append(summblock)

        elif doctype == "hommodule":
            body.append(summblock)
            body.extend(functions.find_by_type(block, "values_item_group"))

        elif doctype == "hommethod":
            body.extend([
                {"type": "summary",
                 "text": functions.first_subblock_string(block)},
                {"type": "methods_item",
                 "text": block.get("text")},
            ])

        if body:
            doc["instant_doc"] = {"body": body, "type": "instant"}

    def _process_doc(self, pages, path, root, block, doc):
        # Add Houdini-specific fields to each document
        path = paths.basepath(path)
        attrs = block.get("attrs", {})

        doctype = attrs.get("type", "").strip()
        context = attrs.get("context", "").strip().replace(",", "")

        if doctype == "node":
            if context in ("pop", "part") or context.endswith("_state"):
                return
            doc["grams"] += " %s node" % attrs.get("internal", "")

        elif doctype in ("vex", "vexstatement"):
            # Replace #context: all with an explicit list
            if context == "all":
                context = vexcontexts
            doc["grams"] += " vex function"

        elif doctype == "command":
            doc["grams"] += " hscript command"

        elif doctype == "expression":
            doc["grams"] += " expression function"

        elif doctype == "homfunction":
            doc["title"] += "()"

        # Set the category field
        if doc.get("category") == "_":
            if path.startswith("/shelf/"):
                doc["category"] = "tool"
            elif path.startswith("/ref/util/"):
                doc["category"] = "utility"
            elif path.startswith("/gallery/shop/"):
                doc["category"] = "gallery/shop"
            elif doctype == "node":
                doc["category"] = "%s/%s" % (doctype, context)
                doc["grams"] += " %s" % context
            elif doctype == "vexstatement":
                doc["category"] = "vex"
            elif doctype in ("hscript", "expression", "example", "homclass",
                             "hommodule", "homfunction", "vex"):
                doc["category"] = doctype
            else:
                topdir = paths.split_path_parts(path)[0]
                doc["subject"] = dir_to_subject.get(topdir)

        replaces = attrs.get("replaces")
        rsection = functions.subblock_by_id(block, "replaces")
        if rsection:
            rlist = " ".join(link.get("fullpath", "") for link
                             in functions.find_links(rsection))
            if replaces:
                replaces = replaces + " " + rlist
            else:
                replaces = rlist

        doc.update({
            "context": context,
            "helpid": attrs.get("helpid"),
            "superclass": attrs.get("superclass"),
            "version": attrs.get("version"),
            "replaces": replaces or None,
            "examplefor": root.get("examplefor"),
            "examplefile": root.get("examplefile"),
            "group": attrs.get("group"),
        })
        self._add_instant(doc, doctype, attrs, block)

        if pages.use_hou and root is block and path.startswith("/nodes/"):
            from houdinihelp import api

            # Add library path to asset doc
            nodetype = api.path_to_nodetype(path)
            if nodetype:
                defn = nodetype.definition()
                if defn:
                    doc["library_path"] = defn.libraryFilePath()

            # Add example file info for node examples
            if pages.config.get("INDEX_USAGES") and "examplefile" in root:
                otlpath = root["examplefile"]
                filepath = pages.file_path(otlpath)
                usages = usages_for_otl(filepath)
                doc["uses"] = " ".join(usages)

    def _process_method(self, pages, path, root, block, doc):
        blocktype = block.get("type")
        title = self._get_title(root)
        text = self._get_title(block)
        name = text.split("(")[0]
        attrs = block.get("attrs", {})
        replaces = attrs.get("replaces") if attrs else None

        doc["path"] = "%s#%s" % (paths.basepath(path), name)
        doc["title"] = doc["sortkey"] = "%s.%s()" % (title, name)
        doc["grams"] = "%s" % name
        doc["replaces"] = replaces

        if blocktype in ("functions_item", "methods_item"):
            doc["type"] = doc["category"] = "hommethod"
        self._add_instant(doc, doc["type"], attrs, block)

    def _process_property(self, pages, path, root, block, doc):
        name = self._get_title(block)
        attrs = block.get("attrs", {})
        ifdprop = attrs.get("ifdprop") if attrs else None
        hprop = attrs.get("hprop") if attrs else None

        doc["title"] = name
        if hprop and hprop != name:
            doc["grams"] = "%s %s" % (name, hprop)

        summary = functions.first_subblock_string(block)
        if ifdprop:
            summary = "%s (%s)" % (summary, ifdprop)
        doc["summary"] = summary

        # Set the page fragment to the Houdini or IFD property name
        if hprop:
            ident = hprop
        elif ifdprop:
            ident = ifdprop.replace(":", "_")
        else:
            ident = util.make_id(name)

        doc["path"] = "%s#%s" % (paths.basepath(path), ident)
        doc["type"] = doc["category"] = "property"
        self._add_instant(doc, doc["type"], attrs, block)

    def _process_attribute(self, pages, path, root, block, doc):
        line = functions.string(block.get("text")).strip()
        if not line:
            return
        slug = block.get("id", functions.slugify(line))

        doc["title"] = line
        doc["grams"] = "@%s" % line
        doc["instant"] = "%s @%s" % (line, line)
        doc["path"] = "%s#%s" % (paths.basepath(path), slug)
        doc["type"] = doc["category"] = "attribute"
        doc["content"] = functions.string(block.get("body"))

    def _process_env_variable(self, pages, path, root, block, doc):
        doc["type"] = doc["category"] = "env_variable"


# Functions for indexing example usages

def usages_for_otl(otlpath):
    try:
        import hou
    except ImportError:
        return ()

    if not otlpath:
        return ()

    from houdinihelp.api import components_to_path

    # HOM doesn't like backslashes
    otlpath = otlpath.replace("\\", "/")

    cffntn = hou.hda.componentsFromFullNodeTypeName

    pathset = set()
    hou.hda.installFile(otlpath)
    for hdadef in hou.hda.definitionsInFile(otlpath):
        ntype = hdadef.nodeType()
        if ntype:
            for typename in ntype.containedNodeTypes():
                scopeop, ns, corename, version = cffntn(typename)
                p = components_to_path(None, scopeop, ns, corename, version)
                pathset.add(p)
    hou.hda.uninstallFile(otlpath)
    return pathset
