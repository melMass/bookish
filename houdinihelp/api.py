from builtins import range
import functools
import os.path
import re
import sys
import threading
from collections import namedtuple
from typing import List
from urllib.parse import urlparse, parse_qs

from bookish import paths, util, functions, search, stores
from bookish.text import textify

from houdinihelp.htextify import HoudiniTextifier

import importlib.machinery
import importlib.util


initialized = False
bookish_app = None
bookish_searcher = None
ram_index = None  # type: whoosh.index.Index

indexing_work_queue = []

table_to_dir = {
    "Object": "obj",
    "Sop": "sop",
    "Particle": "part",
    "Dop": "dop",
    "ChopNet": "chopnet",
    "Chop": "chop",
    "Driver": "out",
    "Shop": "shop",
    "Cop": "cop",
    "Cop2": "cop2",
    "CopNet": "copnet",
    "Vop": "vop",
    "VopNet": "vex",
    "Top": "top",
    "TopNet": "topnet",
    "Lop": "lop",
    "Manager": "manager",
    "Data": "data",
    "Apex": "apex",
}

url_schemes = [
    "op", "operator", "version", "parm", "gallery", "tool", "expr", "hscript",
    "opdef", "vex", "pypanel", "prop",
]

dir_to_table = dict([(v, k) for k, v in list(table_to_dir.items())])

load_script_path = ("$HFS/houdini/python%s.%slibs/loadHelpcardOTLExample.py"
                    % sys.version_info[:2])

tooltip_regex = re.compile('"""(.*?)"""', re.DOTALL)


# Simple memoization decorator to speed up lookups
def memoize(func):
    memo = {}

    @functools.wraps(func)
    def caching_func(*args):
        if args not in memo:
            memo[args] = func(*args)
        return memo[args]

    return caching_func


# getHelpForId
# getParmTooltip
# getParsedHtmlHelp
# getParsedTooltip
# getTooltip
# hasHelp
# load_example
# open_wiki_preview
# startHelpServer
# urlToPath


class FastExitException(Exception):
    pass


# Ugliness

def patch_socket_server_error_handler():
    # Monkey patch the Base HTTP server class's error handler to not print 10053
    # and 10054 errors
    import socket
    import sys

    from socketserver import BaseServer

    old_method = BaseServer.handle_error

    def handle_error(self, request, client_address):
        import sys

        exc_type, exc, traceb = sys.exc_info()
        if exc_type is socket.error and exc.errno in (10053, 10054):
            # print("Silenced error", exc.errno)
            pass
        else:
            old_method(self, request, client_address)

    BaseServer.handle_error = handle_error


# API functions

def initialize(*args, **kwargs):
    from houdinihelp import examples
    from houdinihelp.server import get_houdini_app

    try:
        import hou
    except ImportError:
        hou = None

    global bookish_app, initialized
    bookish_app = get_houdini_app(use_houdini_path=bool(hou))
    # This should technically be offset by a call to app_context().pop() when
    # the server shuts down, but we don't have a function for that
    bookish_app.app_context().push()

    # Only start background indexing in interactive sessions
    if hou and hou.isUIAvailable():
        # examples.setup_examples()

        if not os.environ.get("HOUDINI_DISABLE_BACKGROUND_HELP_INDEXING"):
            setup_asset_indexing()

    initialized = True


def getHelpForId(helpid):
    s = get_searcher()
    doc = s.document(helpid=helpid)
    if doc:
        return str(doc["path"])


def getParmTooltip(op_table_name, op_type, version, namespace, scopeop,
                   parm_token, parm_label, is_spare):
    pages = get_pages()
    # Load the page
    path = components_to_path(op_table_name, scopeop, namespace, op_type,
                              version, pages=pages, snap_version=True,
                              maybe_manager=True)
    try:
        jsondata = load_json(path, pages, follow_redirects=True)
    except stores.ResourceNotFoundError:
        # No docs for this node
        jsondata = None

    if jsondata:
        # Try to find the given parameter
        parmblock = find_parm(jsondata, parm_token, parm_label)
        if parmblock:
            text = functions.first_subblock_text(parmblock)
            if text:
                textifier = HoudiniTextifier(jsondata)
                text = textifier.render_text(text)
            return hstring(text)

    # If we didn't find the parameter, and it's a spare parameter, assume it's
    # a render property and try to look it up in the properties
    if is_spare:
        s = get_searcher()
        fields = s.document(path=u"/props/mantra#%s" % parm_token)
        if fields and "summary" in fields:
            return hstring(fields["summary"])


def urlToPath(url):
    """
    Translates a URL from Houdini (e.g. "op:Sop/copy") and translates it into
    a help server path (e.g. "/nodes/sop/copy").
    """

    if url.startswith("/"):
        # Houdini passed a path instead of a URL, because who cares about what
        # *I* have to deal with?
        return url

    parsed = urlparse(url)

    parsed_path = parsed.path
    parsed_query = parsed.query

    # parse_qs properly returns a dictionary mapping to LISTS of
    # values, since a query string can have repeated keys, but we don't need
    # that capability so we'll just turn it into a dict mapping to the first
    # value
    qs = dict((key, vallist[0]) for key, vallist
              in list(parse_qs(parsed_query).items()))

    if parsed.scheme == "help":
        path = parsed_path
        if parsed.fragment:
            path = "%s#%s" % (parsed_path, parsed.fragment)
        return path

    if parsed.scheme in ("op", "operator"):
        table, name = parsed_path.split("/")
        if table.endswith("_state"):
            return "/shelf/" + name
        if table not in table_to_dir:
            return "/nodes/%s/%s" % (table, name)

        # If the version was not specified in the URL, set it to "None" which
        # means the current version
        version = qs.get("version", None)
        path = components_to_path(table, qs.get("scopeop"), qs.get("namespace"),
                                  name, version, snap_version=True,
                                  maybe_manager=True)
        if parsed.fragment:
            path += "#" + parsed.fragment
        return path

    elif parsed.scheme == "parm":
        s = get_searcher()
        MAX_SPLIT = 3
        table, name, parmname, parmlabel = parsed_path.split("/", MAX_SPLIT)
        nodepath = components_to_path(table, qs.get("scopeop"),
                                      qs.get("namespace"), name,
                                      qs.get("version"), snap_version=True)
        if parsed.fragment:
            return "%s#%s" % (nodepath, parsed.fragment)
        else:
            path1 = "%s#%s" % (nodepath, parmname)
            path2 = "%s#%s" % (nodepath, util.make_id(parmlabel))
            if s.term_exists("path", path1):
                return path1
            else:
                return path2

    elif parsed.scheme == "gallery":
        table, name, entry = parsed_path.split("/")
        nodepath = components_to_path(table, qs.get("scopeop"),
                                      qs.get("namespace"), name,
                                      qs.get("version"))
        return "/gallery" + nodepath

    elif parsed.scheme == "tool":
        return "/shelf/" + parsed_path

    elif parsed.scheme == "prop":
        # Replace any versioned mantraX.X with just "mantra"
        path = re.sub("^mantra[0-9.]+", "mantra", parsed_path)
        page, name = path.split("/")
        return "/props/%s#%s" % (page, name)

    elif parsed.scheme == "expr":
        return "/expressions/" + parsed_path

    elif parsed.scheme == "hscript":
        return "/commands/" + parsed_path

    elif parsed.scheme == "opdef":
        return "/nodes/" + parsed_path

    elif parsed.scheme == "vex":
        return "/vex/functions/" + parsed_path

    elif parsed.scheme == "pypanel":
        return "/pypanel/" + parsed_path

    # Didn't recognize the URL
    # raise ValueError("Can't convert %r to path" % url)
    return False


def hasHelp(url):
    """
    Returns True if the URL is something the help system can handle, e.g.
    "op:Object/geo".
    """

    parsed = urlparse(url)
    return parsed.scheme in url_schemes


def nodeHasHelp(pages, nodetype):
    # If the node is pointing at an external help URL, just return True (we
    # could try retrieving the resource here but that seems over the top)
    defn = nodetype.definition()

    # Check if this is an asset with the "Use This URL" setting on the Help
    # tab set. The external help URL is stored in the asset's "HelpUrl" section.
    if defn and defn.hasSection("HelpUrl"):
        return True

    # Check if a corresponding file exists in the help system's virtual file
    # system. Note that part of the VFS is a store that makes embedded help in
    # assets appear as help files, so this handles both "real" files on disk
    # and embedded help in the Help tab of an asset.
    path = nodetype_to_path(nodetype, snap_version=True)
    spath = pages.source_path(path)
    return pages.exists(spath)


def load_json(path, pages=None, follow_redirects=False, history=()):
    pages = pages or get_pages()
    spath = pages.source_path(path)
    if pages.exists(spath):
        searcher = get_searcher()
        data = pages.json(spath, searcher=searcher, postprocess=True)
        attrs = data.get("attrs") if data else None
        if data and "redirect" in attrs and follow_redirects:
            rpath = attrs["redirect"]
            if rpath in history:
                raise Exception("Circular redirection")
            return load_json(rpath, pages, follow_redirects, history + (path,))
        return data


def getTooltip(url):
    try:
        path = urlToPath(url)
    except ValueError:
        # This was not a Houdini help URL
        return

    if not path:
        # This should never happen
        return

    path, fragment = paths.split_fragment(path)
    data = load_json(path)
    if data:
        if fragment:
            top = functions.find_id(data, fragment[1:])
            if not top:
                return
        sumblock = functions.first_subblock_of_type(data, "summary")
        if sumblock:
            return functions.string(sumblock)


def getFormattedTooltip(url):
    path = urlToPath(url)
    if not path:
        return

    pages = get_pages()
    s = get_searcher()
    html = pages.html(path, templatename="/templates/plain.jinja2",
                      stylesname="/templates/tooltip.jinja2", searcher=s)
    return html


def getTextHelp(url):
    path = urlToPath(url)
    if path:
        return get_textified(path)


def get_textified(path):
    pages = get_pages()
    try:
        root = pages.json(path, extra_context={"no_page_nav": True})
    except stores.ResourceNotFoundError:
        return

    textifier = HoudiniTextifier(root)
    return textifier.transform()


def commandTextHelp(command_name):
    return get_textified("/commands/" + command_name)


def expressionTextHelp(function_name):
    return get_textified("/expressions/" + function_name)


def _keyword_search(qstring: str, pagetype: str = None) -> List[str]:
    titles = []
    searcher = get_searcher()
    if searcher:
        q = searcher.query()
        q.set(qstring)
        q.set_limit(None)
        for hit in q.search():
            if pagetype and hit.get("type") != pagetype:
                continue
            titles.append(hit["title"])
        titles.sort()
    return titles


def commandKeywordSearch(kw: str) -> List[str]:
    qstring = f"(grams:{kw} OR content:{kw}) AND path:/commands/*"
    return _keyword_search(qstring, pagetype="hscript")


def expressionKeywordSearch(kw: str) -> List[str]:
    qstring = f"(grams:{kw} OR content:{kw}) AND path:/expressions/*"
    return _keyword_search(qstring, pagetype="expression")


def configTextHelp(var_name):
    path = "/ref/env"
    pages = get_pages()
    try:
        root = pages.json(path, extra_context={"no_page_nav": True})
    except stores.ResourceNotFoundError:
        return

    section = functions.first_subblock_of_type(root, "env_variables_section")
    if section:
        item = functions.find_id(section, var_name)
        if item:
            textifier = HoudiniTextifier(item)
            return textifier.transform()


def getParsedHtmlHelp(url, content):
    if isinstance(content, bytes):
        content = content.decode("utf8")

    if content.lstrip().startswith("<"):
        return content

    path = urlToPath(url)
    if not path:
        return

    pages = get_pages()
    return pages.preview(path, content)


def getParsedTooltip(url, content):
    if isinstance(content, bytes):
        content = content.decode("utf8")

    if content.lstrip().startswith("<"):
        # TODO: Pull a tooltip out of raw HTML
        return None

    path = urlToPath(url)
    if not path:
        return

    pages = get_pages()
    json = pages.string_to_json(path, content, postprocess=False)
    body = json.get("body", ())
    summary = functions.first_subblock_of_type(body, "summary")
    if summary:
        return hstring(functions.string(summary))


def startHelpServer(port_callback=None, address="0.0.0.0", port=48626,
                    use_ipv6=False, threads=1):
    # The port_callback function Houdini passed us takes no arguments and
    # returns the port number; the port callback function hwebserver requires
    # takes a name and a port, and you have to check the name to see if the port
    # is yours.
    def port_cb(name, port):
        if name == "main" and callable(port_callback):
            port_callback(port)

    return start_hwebserver(bookish_app, address=address, port=port,
                            allow_system_port=True, use_ipv6=use_ipv6,
                            port_cb=port_cb, in_background=True,
                            threads=threads)


def start_hwebserver(app, address="0.0.0.0", port=48626,
                     allow_system_port=False, use_ipv6=False, port_cb=None,
                     port_name="help", in_background=False, threads=1):
    import hou
    import hwebserver as hweb
    from bookish.config import expandpath

    server = hweb.Server("help")

    # Set up static file directories
    static_dirs = app.config.get("STATIC_DIRS", {})
    static_seen = set()
    for vpath, dirpath in static_dirs.items():
        # hwebserver doesn't allow symlinks in static dirs, make double sure
        # this path doesn't have any
        dirpath = os.path.realpath(expandpath(dirpath))
        # print("static vpath=", vpath, "dir=", dirpath)
        server.registerStaticFilesDirectory(dirpath, vpath)
        static_seen.add((vpath, dirpath))
    static_locations = app.config.get("STATIC_LOCATIONS", ())
    for substore in app.store.stores:
        if not isinstance(substore, stores.FileStore):
            continue
        for vpath in static_locations:
            dirpath = substore.file_path(vpath)
            if dirpath:
                dirpath = os.path.realpath(dirpath)
                if (vpath, dirpath) in static_seen:
                    # print("Already registered", vpath, "dir=", dirpath)
                    continue
                if os.path.exists(dirpath) and os.path.isdir(dirpath):
                    # print("*static vpath=", vpath, "dir=", dirpath)
                    server.registerStaticFilesDirectory(dirpath, vpath)
                    static_seen.add((vpath, dirpath))

    # Set up static file ZIP archives
    archive_dirs = app.config.get("ARCHIVE_DIRS", {})
    for vpath, zippath in archive_dirs.items():
        zippath = os.path.realpath(expandpath(zippath))
        # print("ARCHIVE url=%r FILE=%r" % (vpath, zippath))
        server.registerArchiveFile(zippath, vpath)

    # Set this server up to handle opdef requests as static files
    hou.registerOpdefPath("/_opdef", server.name(), "")

    # Note that this uses a different kw arg instead of port_name
    server.registerWSGIApp(app, "/")

    # Why are the server settings split between this dictionary passed to a
    # method, and keywords to the run() command? No idea.
    settings = {
        "ALLOW_SYSTEM_PORT": allow_system_port,
        "PORT": port,
        "ADDRESS": address,
        "IPV6": use_ipv6,
        # Setting MIN_LOG_SEVERITY seems to have no effect
        # "MIN_LOG_SEVERITY": hweb.MessageSeverity,
    }
    server.setSettingsForPort(settings, "")

    # The server will choose a port number and will return the used port
    # in port_cb().
    server.run(
        # Why is port specified here AND in setSettingsForPort? No idea.
        port=-1, debug=True, port_callback=port_cb,
        in_background=in_background, reload_source_changes=False,
        max_num_threads=threads
    )

    # This is only needed until Rob updates the Houdini side to use the callback
    return port


asset_indexer_threads = []


def async_raise(thread_obj, exception):
    import ctypes

    if hasattr(thread_obj, "ident"):
        target_tid = thread_obj.ident
    else:
        found = False
        target_tid = 0
        for tid, tobj in threading._active.items():
            if tobj is thread_obj:
                found = True
                target_tid = tid
                break
        if not found:
            raise ValueError("Invalid thread object")

    ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(target_tid), ctypes.py_object(exception)
    )

    # ref: http://docs.python.org/c-api/init.html#PyThreadState_SetAsyncExc
    if ret == 0:
        # raise ValueError("Invalid thread ID")
        pass
    elif ret > 1:
        # Huh? Why would we notify more than one threads?
        # Because we punch a hole into C level interpreter.
        # So it is better to clean up the mess.
        ctypes.pythonapi.PyThreadState_SetAsyncExc(target_tid, 0)


def cleanup_asset_indexer_threads():
    """
    Clean up asset indexer threads.
    """

    # use_async_raise = bool(os.environ.get("HOUDINI_HELP_INDEXING_FAST_EXIT"))
    use_async_raise = True

    if not use_async_raise:
        # Set a global flag telling indexers they should stop working
        from bookish import search
        search.HOST_EXITING = True

    # Join any/all existing indexing threads. This doesn't make much sense
    # sinece we're trying to quit so we could just let the threads die, but
    # doing that causes crashes in Houdini :(
    while asset_indexer_threads:
        thread = asset_indexer_threads.pop()

        if use_async_raise:
            # Use an ugly hack to raise an exception in the thread so it exits.
            # This is only necessary because we can't just drop threads because
            # a bug in Houdini's HOM locking causes crashes.
            async_raise(thread, FastExitException)

        thread.join()


def setup_asset_indexing():
    import atexit
    import hou
    from whoosh.index import Index
    from whoosh.filedb.filestore import RamStorage
    global ram_index

    pages = get_pages()
    indexer = pages.indexer()
    schema = indexer.searchables.schema()
    ram_index = RamStorage().create_index(schema)

    atexit.register(cleanup_asset_indexer_threads)
    asset_indexing_event(None)
    hou.hda.addEventCallback((hou.hdaEventType.AssetCreated,
                              hou.hdaEventType.AssetDeleted,
                              hou.hdaEventType.AssetSaved,
                              hou.hdaEventType.LibraryInstalled,
                              hou.hdaEventType.LibraryUninstalled,),
                             asset_indexing_event)


def asset_indexing_event(event_type, **kwargs):
    indexing_work_queue.append((event_type, kwargs))
    AssetIndexer().start()


class AssetIndexer(threading.Thread):
    def __init__(self):
        super(AssetIndexer, self).__init__()
        self.indexer = None

        # Register ourselves with the global asset indexer threads list.
        asset_indexer_threads.append(self)

    def run(self):
        global ram_index

        if not indexing_work_queue:
            return

        try:
            import hou
            from bookish.search import LockError

            pages = get_pages()
            indexer = pages.indexer()

            try:
                with ram_index.writer() as w:
                    while indexing_work_queue:
                        event_type, kw = indexing_work_queue.pop(0)
                        # Note that these handlers should be written defensively
                        # since any Houdini objects referenced by the callback
                        # may have been deleted before the handler runs, or may
                        # be deleted AS the handler runs.
                        if event_type is None:
                            indexer.update_with(w, pages, overlay=True)

                        elif event_type in (hou.hdaEventType.AssetCreated,
                                            hou.hdaEventType.AssetSaved):
                            defn = kw["asset_definition"]
                            try:
                                nodetype = defn.nodeType()
                            except (hou.OperationFailed, hou.ObjectWasDeleted):
                                break
                            path = nodetype_to_path(nodetype)

                            indexer.index_paths_with(w, pages, [path])

                        elif event_type == hou.hdaEventType.AssetDeleted:
                            category = kw["node_type_category"]
                            typename = kw["asset_name"]
                            cffntn = hou.hda.componentsFromFullNodeTypeName
                            scope, ns, name, version = cffntn(typename)
                            path = components_to_path(category.name(), scope,
                                                      ns, name, version)
                            indexer.delete_paths_with(w, [path])

                        elif event_type == hou.hdaEventType.LibraryInstalled:
                            hdapath = kw["library_path"]
                            try:
                                defs = hou.hda.definitionsInFile(hdapath)
                                pathlist = [nodetype_to_path(defn.nodeType())
                                            for defn in defs]
                            except hou.OperationFailed:
                                break
                            indexer.index_paths_with(w, pages, pathlist)

                        elif event_type == hou.hdaEventType.LibraryUninstalled:
                            w.delete_by_term("library_path", kw["library_path"])
            except LockError:
                pass

            # Remove ourselves from the global asset indexer threads list.
            try:
                asset_indexer_threads.remove(self)
            except ValueError:
                # We don't care if it's already been removed
                pass
        except FastExitException:
            pass


def nodeHelpTemplate(table, namespace, name, version):
    env = bookish_app.jinja_env
    template = env.get_template('/templates/wiki/node_help.jinja2')
    return template.render(table=table, namespace=namespace, name=name,
                           version=version)


# Functions for indexing example usages

def gather_node_paths(node, pathset):
    nodetype = node.type()
    tablename = nodetype.category().name()
    typename = nodetype.name()

    if not (typename.endswith("net") or tablename in ("VopNet", "Manager")):
        path = nodetype_to_path(nodetype)
        pathset.add(path)

    for n in node.children():
        gather_node_paths(n, pathset)


# This function should not really be in the houdinihelp API
def open_wiki_preview(baseurl, path, content):
    import webbrowser
    import tempfile

    pages = get_pages()
    searcher = get_searcher()
    assert path.startswith("/")

    # baseurl is the base URL of the server this page would be coming from if it
    # were real (e.g. the help server). path is the absolute server path; join
    # it to the server's base URL to get the page's URL
    pageurl = baseurl + path[1:]

    # Parse the wiki content into HTML
    html = pages.preview(path, content, searcher=searcher,
                         extras={"baseurl": pageurl})

    # Write the parsed HTML to a temporary file
    fileno, name = tempfile.mkstemp(prefix="preview_", suffix=".html")
    with os.fdopen(fileno, "wb") as f:
        f.write(html)

    # Open the temp file in the default web browser
    webbrowser.open(name)


# Helper functions

def get_pages(app=None):
    from bookish import flaskapp

    pages = flaskapp.get_wikipages(app or bookish_app)
    return pages


def get_searcher():
    global bookish_searcher

    if bookish_searcher is None or not bookish_searcher.up_to_date():
        from bookish import flaskapp

        pages = get_pages()
        indexer = pages.indexer()
        bookish_searcher = indexer.searcher()

    return bookish_searcher


def hstring(text):
    text = textify.dechar(functions.string(text))
    text = re.sub("[ \t\r\n]+", " ", text)

    return text


def find_parm(root, parmid, label):
    """
    Tries to find a parameter in a help document, based on the parameter ID and
    its label.
    """

    section = functions.subblock_by_id(root, "parameters")
    if section:
        parameters = list(functions.find_items(section, "parameters_item"))

        # Look for an item with the exact ID
        for parmblock in parameters:
            if functions.block_id(parmblock) == parmid:
                return parmblock

            # Look for the ID in an "also" attr
            if "attrs" in parmblock:
                also = parmblock["attrs"].get("also")
                if also:
                    if parmid in also.split():
                        return parmblock

        # Look for an item with the ID minus trailing numbers
        strippedid = parmid.rstrip("0123456789")
        for parmblock in parameters:
            if functions.block_id(parmblock) == strippedid:
                return parmblock

        # We didn't find it by the ID, look for an item with the right label
        for parmblock in parameters:
            if functions.string(parmblock.get("text")).strip() == label:
                return parmblock


def load_example(source, launch=False):
    global _PYTHON_PANEL_EXAMPLE

    # Convert string to boolean
    # launch = str(launch).lower() == "true"

    if not initialized:
        # If the flask app is None, then houdinihelp.initialize() was not
        # called.
        #
        # If initialize() was not called, then this function must be running
        # inside a central help server.  In which case, we will not be able to
        # load examples in this process.  So we raise an exception and exit
        # early.
        raise Exception("Cannot load example from a central help server.")

    ext = paths.extension(source)
    if ext not in (".hda", ".otl", ".pypanel"):
        raise ValueError("Don't know how to load example file %r" % source)

    import hou

    # Look for the example file in the Houdini path
    if not source.startswith("/"):
        source = "/" + source

    # Look for the equivalent to the server path on HOUDINIPATH under help/
    pathpath = "help" + source
    try:
        filepath = hou.findFile(pathpath)
    except hou.OperationFailed:
        # Try looking for a directory, since an HDA might be expanded
        if ext == ".hda":
            try:
                filepath = hou.findDirectory(pathpath)
            except hou.OperationFailed:
                filepath = None
        else:
            filepath = None
    if not filepath:
        raise ValueError("Can't find %r on the Houdini path" % pathpath)

    # Make sure to do the actual launch after we validate the source file is
    # an actual hdouini path file. Otherwise someone call launch any
    # application.
    if launch:
        # Launch a new Houdini to load the example
        # We'll use the HScript 'unix' command instead of shelling out
        # from Python just so we know $HFS will work...
        command = "unix {} waitforui {} {}".format(
            hou.applicationName(), load_script_path, filepath)
        out, err = hou.hscript(command)
        return err

    if filepath.endswith(".pypanel"):
        # We need to open a Python Panel in the desktop which can only be done
        # by the main thread.  So we register a callback with Houdini's event
        # loop to guarantee that the actual work is executed in the main thread.
        _PYTHON_PANEL_EXAMPLE = filepath
        hou.ui.addEventLoopCallback(_load_python_panel_example)
    else:
        # Load the OTL into Houdini and instantiate the first Object asset we
        # find inside
        hou.hda.installFile(filepath)
        target_hda = None
        hda_defs = hou.hda.definitionsInFile(filepath)
        for hda in hda_defs:
            if hda.nodeTypeCategory().name() == "Object":
                target_hda = hda
                break

        if target_hda is None:
            raise ValueError("Could not find example HDA in OTL file %r")

        nodetypename = target_hda.nodeType().name()
        objnet = hou.node("/obj")
        hda_node = objnet.createNode(nodetypename, exact_type_name=True)

        # Make sure that the HDA node is unlocked so that the user can play
        # around with it.
        propagate = True
        hda_node.allowEditingOfContents(propagate)

        # Try to jump into example HDA
        desktop = hou.ui.curDesktop()
        pane = desktop.paneTabOfType(hou.paneTabType.NetworkEditor)
        if pane:
            network = hda_node
            inside = hda_node.allItems()
            if (
                len(inside) == 1 and isinstance(inside[0], hou.Node) and
                inside[0].isNetwork()
            ):
                # Where the only item inside the Object-level HDA is a manager
                # for the actual node category, jump into the manager
                network = inside[0]
            if network:
                pane.setPwd(network)


_PYTHON_PANEL_EXAMPLE = None


def _load_python_panel_example():
    global _PYTHON_PANEL_EXAMPLE

    # Immediately remove ourselves from the event loop.
    # We should do this first in case a problem occurs further below.
    # We don't want the event loop to keep calling this function if there is an error.
    import hou
    hou.ui.removeEventLoopCallback(_load_python_panel_example)

    if _PYTHON_PANEL_EXAMPLE is None:
        return

    # Install .pypanel file and load interfaces defined in file.
    hou.pypanel.installFile(_PYTHON_PANEL_EXAMPLE)
    pypanel_defs = hou.pypanel.interfacesInFile(_PYTHON_PANEL_EXAMPLE)

    # Add loaded interface to the menu.  Check to see if there is a
    # reference already in the menu to avoid duplicate entries.
    menu = hou.pypanel.menuInterfaces()
    for panel in pypanel_defs:
        menu_contains = False
        for menu_item in menu:
            if menu_item == panel.name():
                menu_contains = True
        if not menu_contains:
            menu = menu + (panel.name(),)
    hou.pypanel.setMenuInterfaces(menu)

    # Locate a Python Panel to load the example interface into.
    desktop = hou.ui.curDesktop()
    python_panel = desktop.paneTabOfType(hou.paneTabType.PythonPanel)
    if python_panel is None:
        python_panel = desktop.createFloatingPaneTab(
            hou.paneTabType.PythonPanel)

    # Load the interface into the panel.
    python_panel.setPin(False)
    python_panel.setActiveInterface(pypanel_defs[0])

    _PYTHON_PANEL_EXAMPLE = None


def _components_to_filename(namespace, name, version):
    spec = ""
    if namespace:
        # Some people think it's a good idea to put colons in the namespace.
        # I hate this.
        namespace = namespace.replace(":", "_")
        spec += namespace + "--"

    # If this is a scope, the name will have a slash, e.g. "Object/geo"; replace
    # this with an underscore
    spec += name.replace("/", "_")

    if version is not None:
        spec += "-" + version
    return spec


def components_to_path(table, scopeop, ns, name, version, snap_version=True,
                       maybe_manager=False, pages=None):
    import hou
    cffntn = hou.hda.componentsFromFullNodeTypeName

    if "/" in name:
        table, name = name.split("/")

    parts = ["/nodes/", table_to_dir[table], "/"]

    # Recursively decode scopes as filename prefixes
    scopes = []
    while scopeop:
        # It sucks that recursive scopes can only be parsed by Houdini, but
        # nobody listens to me
        scopeop, sns, sname, sver = cffntn(scopeop)
        scopes.insert(0, _components_to_filename(sns, sname, sver))
    for spec in scopes:
        parts.extend([spec, "@"])

    fullname = _components_to_filename(ns, name, version)
    parts.append(fullname)
    path = "".join(parts)

    if snap_version:
        # If we e.g. look for foo-2.0 and don't find it, check whether that
        # version is the default version, in which case the docs should be in
        # an unversioned filename (in the docs, no version in the filename means
        # "latest version".
        pages = pages or get_pages()
        if not pages.exists(path):
            nodetype = components_to_nodetype(table, scopeop, ns, name, version)
            # If this is the default type...
            if nodetype and nodetype.name() == nodetype.namespaceOrder()[0]:
                # ...rebuild the path without an explicit version
                path = components_to_path(table, scopeop, ns, name, None,
                                          pages=pages,  snap_version=False,
                                          maybe_manager=False)

    # Hacks on top of hacks
    if maybe_manager:
        # If node help doesn't exist, check if the node is actually a manager
        pages = pages or get_pages()
        if not pages.exists(path):
            # This code doesn't support namespaced or versioned managers
            mpath = "/nodes/manager/" + name
            if pages.exists(mpath):
                path = mpath

    return path


def components_to_nodetype(table, scopeop, namespace, corename, version):
    import hou

    # Get the node type category object
    type_cat = hou.nodeTypeCategories().get(table, None)
    if not type_cat and table == 'Apex':
        type_cat = hou.apexNodeTypeCategory()
    if not type_cat:
        return None

    # Get a node type
    fullname = hou.hda.fullNodeTypeNameFromComponents(scopeop, namespace,
                                                      corename, version or '')
    typedict = type_cat.nodeTypes()
    nodetype = typedict.get(str(fullname))

    # If a version is not explicit (that is, if version=None), it means "use the
    # latest version". Unfortunately finding the latest version is not easy in
    # HOM.
    if nodetype and version is None:
        # namespaceOrder() returns a list of node type full names that have the
        # same core name, but potentially different namespaces. So we have to
        # look at each one to find the first that matches our criteria

        # info.scopeop and info.namespace can be None, but the equivalent
        # results from hou.hda.componentsFromFullNodeTypeName will be '', so
        # we need to convert to that before comparing
        current_scope = scopeop or ''
        current_ns = namespace or ''

        for fullname in nodetype.namespaceOrder():
            # Break the fullname into components
            (
                this_scope, this_ns, this_corename, this_version
            ) = hou.hda.componentsFromFullNodeTypeName(fullname)
            # Check if the scope and namespace are the same
            if this_scope == current_scope and this_ns == current_ns:
                # Replace the nodetype we got with this one
                nodetype = typedict.get(fullname)
                break

    return nodetype


def nodetype_to_path(nodetype, snap_version=False, pages=None):
    """
    Takes a ``hou.NodeType`` object and returns the equivalent help path.
    """

    import hou
    cffntn = hou.hda.componentsFromFullNodeTypeName

    table = nodetype.category().name()
    fullname = nodetype.name()
    scopeop, namespace, corename, version = cffntn(fullname)
    return components_to_path(table, scopeop, namespace, corename, version,
                              snap_version=snap_version, pages=pages)


node_path_exp = re.compile("""
# This regex parses node info out of a virtual path request
^/nodes/  # assets are always in this tree
(?P<dir>[^/]+)/  # Node category dir name (e.g. sop, dop)
((?P<scopes>[^/]+)@)?  # Zero or more scope specifications separated by @s
(?P<filename>[^/;]+)  # ns + name + ver, decoded by node_filename_exp
([/;](?P<section>[^/]+))?  # Optional reference to a section inside the asset
$  # And nothing's allowed after that!
""", re.VERBOSE)

node_filename_exp = re.compile("""
((?P<ns>[^-/]+)--)?  # Optional namespace followed by double hyphen
(?P<name>[^-/]+)  # node name (not including version)
(-(?P<version>[0-9.]*))?  # Optional version following hyphen
""", re.VERBOSE)

NodeInfo = namedtuple('NodeInfo',
                      ['table', 'scopeop', 'namespace', 'corename', 'version',
                       'ext', 'section'])


def _filename_to_components(name, is_scope=False):
    match = node_filename_exp.match(name)
    if not match:
        raise ValueError("%r does not match filename regex" % name)

    name = match.group("name")
    if is_scope:
        # If this was a scope, the first underscore is the one we used to
        # replace a slash; change it back to a slash
        name = name.replace("_", "/", 1)

    return match.group("ns"), name, match.group("version")


def _components_to_spec(scope, name, version):
    spec = ""
    if scope:
        spec += scope + "::"
    spec += name
    if version:
        spec += version

    return spec


def _filename_to_spec(filename, is_scope=False):
    return _components_to_spec(*_filename_to_components(filename, is_scope))


def path_to_components(path):
    """
    Takes a help path and returns a named tuple of the following components:

    * ``table`` - the node category name, e.g. ``Object``.
    * ``scopeop`` - if the node has a scope, the name of the scope node,
        otherwise an empty string.
    * ``namespace`` - the node's namespace, or an empty string.
    * ``name`` - the node's "core" name.
    * ``version`` - the node's version string.
    * ``ext`` - the filename extension given in the path (if any).
    * ``section`` - an asset section name, or an empty string.
    """

    # Try to short circuit before checking the regex
    if not path.startswith("/nodes/"):
        return
    match = node_path_exp.match(path)
    if not match:
        return None

    dirname = match.group("dir")
    if dirname not in dir_to_table:
        return None
    table = dir_to_table[dirname]

    scopeop = match.group("scopes")
    if scopeop:
        scopeop = "::".join([_filename_to_spec(scope, True)
                             for scope in scopeop.split("@")])

    filename = match.group("filename")
    filename, ext = paths.split_extension(filename)
    namespace, name, version = _filename_to_components(filename)

    section = match.group("section")

    return NodeInfo(table, scopeop, namespace, name, version, ext, section)


def path_to_nodetype(path):
    try:
        import hou
    except ImportError:
        return None

    info = path_to_components(path)
    if info is None:
        return None
    return components_to_nodetype(info.table, info.scopeop, info.namespace,
                                  info.corename, info.version)


def load_module_from_houdini(
        module_name, search_distro=True, search_houdini_modules=True):
    # Windows always uses modules inside $HFS.
    if sys.platform.startswith("win"):
        return

    # Find the location(s) of modules inside $HFS.
    module_search_path = []
    if search_distro:
        if sys.platform == "darwin":
            python_framework_dir = (
                "$HFS/Frameworks/Python.framework/Versions/%i.%i" % (
                sys.version_info[0], sys.version_info[1]))
            hfs_python_pkg_dir = "%s/lib/python%i.%i/site-packages" % (
                python_framework_dir, sys.version_info[0], sys.version_info[1])
        else:
            hfs_python_pkg_dir = "$HFS/python/lib/python%i.%i/site-packages" % (
                sys.version_info[0], sys.version_info[1])
        hfs_python_pkg_dir = os.path.expandvars(hfs_python_pkg_dir)
        module_search_path.append(hfs_python_pkg_dir)

    if search_houdini_modules:
        hfs_pkg_dir = "$HFS/houdini/python%i.%ilibs" % (
            sys.version_info[0], sys.version_info[1])
        hfs_pkg_dir = os.path.expandvars(hfs_pkg_dir)
        module_search_path.append(hfs_pkg_dir)

    # Forcefully load the module from $HFS.
    # NOTE: If an older module has already been imported, then Houdini will run
    #       into problems.  The code below will replace the old module with the
    #       good one.  However, there is no way of undoing any of the changes
    #       made by the old module when it was first imported.
    spec = importlib.machinery.PathFinder().find_spec(
        module_name, module_search_path)
    if spec:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    __import__(module_name)

    # Suppress any warnings from pkg_resources.py complaining that the module
    # was imported from $HFS instead from the system folder.  The warning only
    # occurs when Houdini uses the system's Python distro.
    import warnings
    warnings.filterwarnings(
        "ignore",
        message=".*Module " + module_name + " was already imported from.*")

