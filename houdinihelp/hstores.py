from __future__ import print_function
import os.path
import re
from datetime import datetime

from bookish import compat, paths, stores


class HoudiniPathStore(stores.OverlayStore):
    """
    Overlays HOUDINIPATH/help directories onto the virtual file system.
    """

    def __init__(self, path="help"):
        try:
            import hou
            hfs = os.path.abspath(os.environ.get("HFS"))
            hfshelp = os.path.join(hfs, "houdini", "help")

            # Get the list of @/help directories and use that to initialize the
            # OverlayStore
            try:
                dirpaths = hou.findDirectories(path)
            except hou.OperationFailed:
                dirpaths = []

            # Eliminate $HFS/path from the found paths
            if hfs:
                dirpaths = [dp for dp in dirpaths
                            if not os.path.abspath(dp).startswith(hfshelp)]

            self.stores = [stores.FileStore(path) for path in dirpaths]
        except ImportError:
            # On Windows we can run into a scenario where this is loaded as
            # part of the build process for thou 'hou' module.  Needless to
            # say that will cause a conflict even though it's not a critical
            # error
            self.stores = []

    def tags(self):
        return ("requires_hou",)


def _manager_redirect(store, path):
    if not path.startswith("/nodes/"):
        return
    if store.exists(path):
        return

    parts = paths.split_path_parts(path)
    if len(parts) == 3:
        parts[1] = "manager"
        newpath = "/" + "/".join(parts)
        if store.exists(newpath):
            return newpath


class FixedFileStore(stores.FileStore):
    def __init__(self, dirpath, config=None, exemplar=None):
        super(FixedFileStore, self).__init__(
            stores.expandpath(dirpath), config=config
        )

        slm = super(FixedFileStore, self).last_modified
        if exemplar:
            try:
                self.fixed_time = slm(exemplar)
            except stores.ResourceNotFoundError:
                self.fixed_time = datetime(2001, 1, 1)
        else:
            for path in self.list_all():
                self.fixed_time = slm(path)
                break
            else:
                self.fixed_time = datetime(2001, 1, 1)

    def last_modified(self, path):
        return self.fixed_time


class HiddenNodeStore(stores.HideStore):
    # Don't use this -- hidden nodes should not be indexed, but they should
    # still be readable

    def explain(self, path, tab=0):
        from houdinihelp import api

        self.dump(tab)
        self.emit(tab, "path=", path)
        if path.startswith("/nodes/"):
            nodetype = api.path_to_nodetype(path)
            if nodetype:
                self.emit(tab, "hidden=", nodetype.hidden())
        self.emit(tab, "exists=", self.exists(path))

    def _check(self, path):
        from houdinihelp import api

        if path.startswith("/nodes/"):
            nodetype = api.path_to_nodetype(path)
            if nodetype and nodetype.hidden():
                return False

        return True

    def redirect(self, path):
        return _manager_redirect(self.child, path)


class ManagerRedirectStore(stores.WrappingStore):
    def redirect(self, path):
        return _manager_redirect(self.child, path)


class AssetStore(stores.StringStore):
    """
    Maps assets (and HDK nodes with embedded help) onto paths under /nodes/ in
    the virtual file system.
    """

    def tags(self):
        return ("requires_hou",)

    @staticmethod
    def _path_to_nodetype(path):
        from houdinihelp import api

        nodetype = api.path_to_nodetype(path)
        if not nodetype:
            raise stores.ResourceNotFoundError(path)

        return nodetype

    @staticmethod
    def _should_ignore(nodetype):
        # Ignore hidden node types
        if nodetype.hidden():
            return True

        # Ignore node types that don't have embedded help
        hdadef = nodetype.definition()
        if hdadef and not hdadef.isCurrent():
            return True

        return False

    def exists(self, path):
        from houdinihelp import api

        if hasattr(self, "_staticpaths"):
            _staticpaths = self._staticpaths
        else:
            _staticpaths = self._staticpaths = set(("/", "/nodes", "/nodes/"))
            for dirname in api.dir_to_table:
                _staticpaths.add("/nodes/%s" % dirname)
                _staticpaths.add("/nodes/%s/" % dirname)
        if path in _staticpaths:
            return True

        try:
            nodetype = api.path_to_nodetype(path)
        except ValueError:
            return False

        if nodetype and not self._should_ignore(nodetype):
            info = api.path_to_components(path)
            if info.section:
                # The path specified a specific section in an HDA
                hdadef = nodetype.definition()
                return hdadef and info.section in hdadef.sections()

            # The path did not specify a section, meaning it's asking for the
            # help. The path is only valid if it's asking for the .txt source
            # (since that's the only conceptual "file" available)
            return path.endswith(".txt") and nodetype.embeddedHelp()

        return False

    def list_all(self, path="/", no_lang=False):
        import hou
        from houdinihelp import api

        # Previously we searched every HDA for help, but now that we need to
        # get help from HDK nodes as well, we have to look at every node type
        catdict = hou.nodeTypeCategories()
        for typecat in sorted(catdict):
            typedict = catdict[typecat].nodeTypes()
            for nodetype in sorted(typedict.values(), key=lambda t: t.name()):
                if self._should_ignore(nodetype):
                    continue
                if not nodetype.embeddedHelp():
                    continue

                # OK, this node's help is in this virtual file tree... compute
                # its path and see if the prefix the user gave matches that path
                nodepath = api.nodetype_to_path(nodetype)
                if nodepath.startswith(path):
                    # nodetype_to_path returns a "virtual path" without an
                    # extension, but this store acts like it contains wiki files
                    # ending in .txt, so add the extension to path we claim
                    # to contain
                    yield nodepath + ".txt"

    def last_modified(self, path):
        nodetype = self._path_to_nodetype(path)
        hdadef = nodetype.definition()
        if hdadef:
            timestamp = hdadef.modificationTime()
            return datetime.utcfromtimestamp(timestamp)
        else:
            # Currently, we always return "now" as the last mod time for HDK
            # nodes.
            # TODO: find a way to return a better value
            return datetime.utcnow()

    def writable(self, path):
        nodetype = self._path_to_nodetype(path)
        # A node is only writeable if it's an asset
        return bool(nodetype.definition())

    def write_file(self, path, bytestring):
        from houdinihelp import api

        nodetype = self._path_to_nodetype(path)
        hdadef = nodetype.definition()
        if not hdadef:
            raise Exception("%r is not an asset" % path)

        info = api.path_to_components(path)
        sections = hdadef.sections()
        section = info.section or "Help"
        if section in sections:
            sections[section].setContents(bytestring)
        else:
            hdadef.addSection(section, bytestring)

    def delete(self, path):
        from houdinihelp import api

        nodetype = self._path_to_nodetype(path)
        hdadef = nodetype.definition()
        if not hdadef:
            raise Exception("%r is not an asset" % path)

        info = api.path_to_components(path)
        section = info.section or "Help"
        if hdadef:
            hdadef.sections()[section].setContents("")

    # def extra_fields(self, path):
    #     nodetype = self._path_to_nodetype(path)
    #     definition = nodetype.definition()
    #     if definition:
    #         return {"library_path": definition.libraryFilePath()}

    def content(self, path, encoding="utf8"):
        from houdinihelp import api

        nodetype = self._path_to_nodetype(path)
        if not nodetype:
            raise stores.ResourceNotFoundError(path)

        info = api.path_to_components(path)
        if info.section:
            hdadef = nodetype.definition()
            if not hdadef:
                raise stores.ResourceNotFoundError(path)
            content = hdadef.sections()[info.section].binaryContents()
        else:
            content = nodetype.embeddedHelp()

        if encoding and isinstance(content, bytes):
            content = content.decode(encoding)

        return content

    def open(self, path, mode="rb"):
        assert mode == "rb"
        content = self.content(path, encoding=None)
        assert isinstance(content, bytes)
        return compat.BytesIO(content)

    def is_dir(self, path):
        return False

    def etag(self, path):
        nodetype = self._path_to_nodetype(path)
        # If the node is an asset, use its modification type as its etag.
        hdadef = nodetype.definition()
        if hdadef:
            return str(hdadef.modificationTime())

    def move(self, path, newpath):
        raise NotImplementedError


class ShelfStore(stores.StringStore):
    """
    A provider which translates requests for help under /shelf/ into calls
    to HOM to load embedded help content from shelf tools.
    """

    prefix = "/shelf/"
    nodeexp = re.compile(prefix + "(.*)[.]txt")

    def __init__(self):
        super(ShelfStore, self).__init__()

    def tags(self):
        return ("requires_hou",)

    def _path_to_tool(self, path):
        match = self.nodeexp.match(path)
        if match:
            import hou
            base, ext = paths.split_extension(match.group(1))
            return hou.shelves.tool(base)

    def list_dir(self, path):
        if path == self.prefix:
            import hou
            return sorted(hou.shelves.tools())
        else:
            return ()

    def exists(self, path):
        # Say this path exists if it starts with /shelf/...
        if path.startswith(self.prefix):
            # And HOM has a tool by this name...
            tool = self._path_to_tool(path)
            if tool:
                # And that tool has some help content. We used to just check
                # if the tool object existed, but then a developer made file
                # help with the same name as the tool and it broke this test,
                # so now we have to be more careful.
                return bool(tool.help())

    def content(self, path, encoding="utf8"):
        tool = self._path_to_tool(path)
        if tool:
            return tool.help()
        else:
            raise stores.ResourceNotFoundError(path)

    def write_file(self, path, bytestring):
        tool = self._path_to_tool(path)
        if tool:
            tool.setHelp(bytestring)
        else:
            raise stores.ResourceNotFoundError(path)

    def delete(self, path):
        self.write_file(path, b"")

    def is_dir(self, path):
        return False

    def move(self, path, newpath):
        raise NotImplementedError


# class RemappingIconStore(stores.WrappingStore):
#     line_expr = re.compile("""
#     ^  # definition must start in first column (no indents!)
#     (?P<ddir>[A-Za-z0-9]*)_(?P<dname>[^ \t:]+)  # "destination" dir and name
#     [ \t]*:=[ \t]*  # Assignment "operator", with optional whitespace
#     (?P<sdir>[A-Za-z0-9]*)_(?P<sname>[^; \t\n]+)  # "source" dir and name
#     [ \t]*;?$  # Line should end with a semicolon
#     """, re.VERBOSE)
#
#     path_expr = re.compile("/(?P<dir>[^/]+)/(?P<name>[^/]+)[.]svg$")
#
#     def __init__(self, child, mappings=None, mapping_path="/IconMapping"):
#         self.child = child
#         self.mappings = mappings or {}
#
#         if mapping_path:
#             self.read_mappings(mapping_path)
#
#     def read_mappings(self, mapping_path):
#         line_exp = self.line_expr
#         mappings = self.mappings
#
#         if self.exists(mapping_path):
#             with self.open(mapping_path) as f:
#                 lines = f.read().decode("utf-8")
#                 for line in lines.split("\n"):
#                     m = line_exp.match(line)
#                     if m:
#                         sdir = m.group("sdir")
#                         sname = m.group("sname")
#                         ddir = m.group("ddir")
#                         dname = m.group("dname")
#                         mappings[ddir, dname] = sdir, sname
#
#     def _mapped_path(self, path):
#         if not path:
#             return
#
#         m = self.path_expr.search(path)
#         if m:
#             dirname = m.group("dir")
#             iconname = m.group("name")
#             try:
#                 dirname, iconname = self.mappings[dirname, iconname]
#             except KeyError:
#                 return
#             else:
#                 repath = ''.join((path[:m.start("dir")],
#                                  dirname, "/", iconname, ".svg"))
#                 if repath != path:
#                     return repath
#
#     def _xlate_down(self, path):
#         if not self.child.exists(path):
#             # _mapped_path() returns None if the icon is not mapped
#             path = self._mapped_path(path) or path
#         return path
#
#     def redirect(self, path):
#         # redirect() should return None if there is no redirect, and
#         # self._mapped returns None if there is no mapping, so just call it
#         # directly
#         return self._mapped_path(path)


# if __name__ == "__main__":
#     from bookish import stores
#
#     fs = stores.FileStore("/Users/dev/src/houdini/support")
#     ris = RemappingIconStore(fs, "/Users/matt/dev/src/houdini/support/icons/IconMapping")
#     for it in ris.mappings.items():
#         print(it)
#     print(ris._xlate_down("/icons/VIEW/quickplane_load_1.svg"))
#     print(ris._xlate_down("/icons/TOP/scheduler.svg"))
#     print(ris._xlate_down("/icons/TOP/merge.svg"))


