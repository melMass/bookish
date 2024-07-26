# Copyright 2017 Matt Chaput. All rights reserved.
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
import errno
import json
import logging
import multiprocessing
import os.path
import tempfile
import weakref

from bookish import compat, functions, paths, search, stores, util
from bookish.wiki import langpaths, pipeline, styles
from bookish.parser import condition_string, ParserContext
from bookish.parser.rules import Miss


# Exceptions

class Redirect(Exception):
    def __init__(self, newpath):
        self.newpath = newpath


class ParserError(Exception):
    pass


# Wiki functions

def span(typename, text, **kwargs):
    assert isinstance(typename, compat.string_type)
    kwargs["type"] = typename
    kwargs["text"] = text
    return kwargs


def block(typename, indent, text, role=None, **kwargs):
    assert isinstance(typename, compat.string_type)
    kwargs["type"] = typename
    kwargs["indent"] = indent
    if text:
        kwargs["text"] = text
    if role is not None:
        kwargs["role"] = role
    return kwargs


# Helper functions

def remove_duplicates(ls):
    out = []
    seen = set()
    for item in ls:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# Parsing functions

def parse_to_blocklist(string):
    from bookish.grammars.wiki import blocks, grammar

    # blocklist = []
    # limit = len(string)
    # i = 0
    # ctx = ParserContext()
    # while i <= limit:
    #     out, newi = blocks(string, i, ctx)
    #     print("    ", out, newi, len(string))
    #     if out is Miss:
    #         print("Parser Error at %d: %r" % (i, string[i-10:i+10]))
    #         raise ParserError
    #     blocklist.append(out)
    #     i = newi
    # return blocklist

    string = condition_string(string)
    out, _ = grammar(string, 0, ParserContext())
    if out is Miss:
        raise ParserError

    return out


def parse_to_root(string):
    return {
        "type": "root",
        "attrs": {},
        "body": parse_to_blocklist(string)
    }


def write_html_output(pages, path, output_dir, cache=True, searcher=None):
    output = pages.html(path, save_to_cache=cache, searcher=searcher)
    if output_dir:
        htmlpath = paths.basepath(path) + ".html"
        filepath = os.path.join(output_dir, htmlpath[1:])
        parentdirpath = os.path.dirname(filepath)
        try:
            os.makedirs(parentdirpath)
        except OSError as exc:
            if exc.errno != errno.EEXIST or not os.path.isdir(parentdirpath):
                raise

        with open(filepath, "wb") as f:
            f.write(output.encode("utf-8"))
    else:
        print(output)


def write_html_output_multi(pages, dirpath, procs, pathlist):
    if procs == 0:
        procs = multiprocessing.cpu_count()
    print("Generating with", procs, "worker processes")

    queue = multiprocessing.Queue()
    procs = [HtmlGenProcess(pages, dirpath, queue) for _ in range(procs)]
    for proc in procs:
        proc.start()
    for path in pathlist:
        queue.put(path)
    for _ in procs:
        queue.put(None)
    for proc in procs:
        proc.join()


class HtmlGenProcess(multiprocessing.Process):
    def __init__(self, pages, dirpath, queue):
        super(HtmlGenProcess, self).__init__()
        # self.pages = pages_from_config(config)
        self.pages = pages
        self.indexer = self.pages.indexer()
        self.searcher = self.indexer.searcher()
        self.dirpath = dirpath
        self.queue = queue

    def run(self):
        pages = self.pages
        dirpath = self.dirpath
        searcher = self.searcher
        queue = self.queue
        while True:
            path = queue.get()
            if path is None:
                return
            print("Process", self.name, "generating", path)
            write_html_output(pages, path, dirpath, searcher=searcher)


# Page cache manager

class PageCache(object):
    ext = ".json"

    def __init__(self, cachedir):
        if not cachedir:
            cachedir = tempfile.mkdtemp(prefix="bookish", suffix=".cache")

        self.cachedir = cachedir
        self.cachestore = stores.FileStore(cachedir)
        # Small "level 1" in-memory cache
        # self.mem_cache_size = mem_cache_size
        # self.memcache = self._make_mem_cache()

    # def _make_mem_cache(self):
    #     return util.DbLruCache(self.mem_cache_size)

    def cache_path(self, path):
        return paths.basepath(path).replace(":", "-") + self.ext

    @staticmethod
    def _cached_dt(store, cstore, sourcepath, cachepath):
        if store.exists(sourcepath) and cstore.exists(cachepath):
            # Check the date on the original
            srcdt = store.last_modified(sourcepath)
            # If the date on the cached version isn't older, return it
            cachedt = cstore.last_modified(cachepath)
            # print("path=", sourcepath, "src=", srcdt, "c=", cachedt)
            if cachedt >= srcdt:
                return cachedt

        # if cachepath in self.memcache:
        #     del self.memcache[cachepath]

    def get_cached_json(self, pages, sourcepath):
        store = pages.store
        cstore = self.cachestore
        cachepath = self.cache_path(sourcepath)
        dt = self._cached_dt(store, cstore, sourcepath, cachepath)
        if not dt:
            return

        # Check for the file in the memory cache
        # if cachepath in self.memcache:
        #     # print(sourcepath, "from mem cache")
        #     return self.memcache.get(cachepath)

        # Load and parse the cached JSON
        jsonstring = self.cachestore.content(cachepath, "utf8")
        try:
            jsondata = json.loads(jsonstring)
        except ValueError:
            # Corrupt cache file???
            return

        # Check the includes for changes
        includes = frozenset(jsondata.get("included", ()))
        for incpath in includes:
            # Get source path for include path
            inc_spath = pages.source_path(incpath)
            # If the include is missing, the cached data is invalid
            if not store.exists(inc_spath):
                # print("  missing include", inc_spath)
                return None
            # If the include is newer, the cached data is invalid
            if dt < store.last_modified(inc_spath):
                # print("newer include:", inc_spath,
                #       self.store.last_modified(inc_spath))
                return None

        # Put it in the memcache and return it
        # self.memcache.put(cachepath, jsondata)
        return jsondata

    def put_cache(self, path, jsondata):
        assert path.startswith("/")
        cachepath = self.cache_path(path)

        bytestring = json.dumps(jsondata).encode("utf8")
        filepath = os.path.join(self.cachedir, cachepath[1:])

        parent = os.path.dirname(filepath)
        if not os.path.exists(parent):
            try:
                os.makedirs(parent)
            except OSError:
                # We couldn't make the cache directory for some reason, so give
                # up on saving the cache at all
                return

        with open(filepath, "wb") as f:
            f.write(bytestring)

    def delete_path(self, path):
        cachepath = self.cache_path(path)
        # if cachepath in self.memcache:
        #     del self.memcache[cachepath]
        filepath = os.path.join(self.cachedir, cachepath[1:])
        os.remove(filepath)

    def empty(self):
        # self.memcache = self._make_mem_cache()
        for cachepath in self.cachestore.list_all():
            filepath = os.path.join(self.cachedir, cachepath[1:])
            os.remove(filepath)


# Setup

def pages_from_config(config, cls=None, jinja_env=None, logger=None):
    store = store_from_config(config)
    jinja_env = jinja_from_config(config, store, jinja_env=jinja_env)
    logger = logger_from_config(config, logger)

    cls = cls or config.get("PAGES_CLASS", WikiPages)
    if isinstance(cls, compat.string_type):
        cls = util.find_object(cls)

    return cls(store, jinja_env, config, logger=logger)


def logger_from_config(config, logger=None):
    logger = logger or logging.getLogger(__name__)
    werk_logger = logging.getLogger('werkzeug')

    if not logger.handlers:
        handler = logging.StreamHandler()
        # If we weren't passed a log file path, see if there's one in the config
        log_file = config.get("LOGFILE")
        # If we have a log file, set up a handler for it
        if log_file:
            log_file = config.expandpath(log_file)
            try:
                handler = logging.FileHandler(log_file)
            except IOError:
                pass

        # Set a formatter because the default is awful
        from logging import Formatter
        handler.setFormatter(Formatter("%(asctime)s: %(message)s"))

        # Set the handler in flask and werkzeug
        logger.addHandler(handler)
        if not werk_logger.handlers:
            werk_logger.addHandler(handler)

    # Set the log level
    log_level = config.get("LOGLEVEL", "INFO")
    # If the log level is a string, convert it
    if isinstance(log_level, str):
        log_level = getattr(logging, log_level.upper())

    logger.setLevel(log_level)
    werk_logger.setLevel(log_level)

    return logger


def store_from_config(config):
    specs = []
    if "DOCUMENTS" in config:
        specs.append(config["DOCUMENTS"])
    if "EXTRA_DOCUMENTS" in config:
        specs.append(config["EXTRA_DOCUMENTS"])
    if "SUPPORT_DOCUMENTS" in config:
        specs.append(config["SUPPORT_DOCUMENTS"])
        
    return stores.store_from_spec(specs)


def jinja_from_config(config, store, jinja_env=None):
    from bookish.functions import functions_dict
    from bookish.coloring import jinja_format_code

    if not jinja_env:
        import jinja2
        jinja_env = jinja2.Environment()

    lexers = config.get("LEXERS", {}).copy()
    for key in lexers:
        value = lexers[key]
        if isinstance(value, compat.string_type):
            lexers[key] = util.find_object(value)

    def format_code(block, lexername=None, pre=False):
        return jinja_format_code(block, lexername=lexername, pre=pre,
                                 extras=lexers)

    store_ref = weakref.ref(store)

    jinja_env.globals.update(functions_dict)
    jinja_env.globals["exists"] = lambda path: store_ref().exists(path)
    jinja_env.globals["format_code"] = format_code
    jinja_env.globals["config"] = config

    jinja_env.loader = styles.JinjaStoreLoader(store)
    return jinja_env


def textifier_from_config(config):
    from bookish.textify import BookishTextifier

    cls = config.get("TEXTIFY_CLASS", BookishTextifier)
    if isinstance(cls, compat.string_type):
        cls = util.find_object(cls)
    return cls
    

# Page manager

class WikiPages(object):
    def __init__(self, store, jinja_env, config, logger=None):
        self.store = store  # stores.CommonLang(store)
        self.jinja_env = jinja_env
        self.config = config

        if not logger:
            logger = logging.getLogger(__name__)
            log_level = config.get("LOGLEVEL", "INFO")
            # If the log level is a string, convert it
            if isinstance(log_level, str):
                log_level = getattr(logging, log_level.upper())
            logger.setLevel(log_level)
        self.logger = logger

        self._pre_pipeline = pipeline.default_pre_pipeline()
        self._post_pipeline = pipeline.default_post_pipeline()
        self._default_style = config.get("WIKI_STYLE", "wiki.jinja2")
        self._default_template = config.get("TEMPLATE", "page.jinja2")
        self._default_lang = config.get("DEFAULT_LANGUAGE", "en")

        self.index_page_name = config.get("INDEX_PAGE_NAME", "index")
        self.wiki_ext = config.get("WIKI_EXT", ".txt")

        self.cache = None
        self.cachedir = config.get("CACHE_DIR")
        if self.cachedir:
            self.cache = PageCache(stores.expandpath(self.cachedir))
        self._parent_cache = {}
        
        self._styles = {}

    def index_dirs(self):
        from whoosh import __version__

        index_dir = stores.expandpath(self.config["INDEX_DIR"])
        index_dir = "%s%s.%s" % (index_dir, __version__[0], __version__[1])
        index_dir = stores.expandpath(index_dir)
        use_dir = index_dir

        dynamic_dir = self.config.get("DYNAMIC_INDEX_DIR")
        if dynamic_dir:
            dynamic_dir = "%s%s.%s" % (dynamic_dir, __version__[0], __version__[1])
            dynamic_dir = stores.expandpath(dynamic_dir)
            if search.WhooshIndexer.index_exists_in(dynamic_dir):
                use_dir = dynamic_dir

        if self.config.get("USE_SOURCE_INDEX"):
            use_dir = index_dir

        return index_dir, dynamic_dir, use_dir

    def indexer(self):
        sables = self.config.get("SEARCHABLES", search.Searchables())
        if isinstance(sables, compat.string_type):
            sables = util.find_object(sables)
        if isinstance(sables, type):
            sables = sables()

        sables.index_page_name = self.index_page_name

        cls = self.config.get("INDEXER_CLASS", search.WhooshIndexer)
        if isinstance(cls, compat.string_type):
            cls = util.find_object(cls)

        _, _, use_dir = self.index_dirs()
        return cls(use_dir, sables, logger=self.logger)

    def reindex(self, clean=False):
        self.logger.info("Reindexing")
        indexer = self.indexer()
        try:
            indexer.update(self, clean=clean)
        except search.LockError:
            self.logger.info("Could not get indexing lock")

    def textifier(self):
        cls = self.config["TEXTIFY_CLASS"]
        if isinstance(cls, compat.string_type):
            cls = util.find_object(cls)
        return cls
    
    def textify(self, jsondata, path="", **kwargs):
        textfier_class = self.textifier()
        textifier = textfier_class(jsondata)
        textifier.path = path
        return textifier.transform(**kwargs)

    def style(self, templatename):
        if templatename in self._styles:
            style = self._styles[templatename]
        else:
            style = styles.Stylesheet(self.jinja_env, templatename,
                                      self.index_page_name)
            self._styles[templatename] = style
        return style

    def full_path(self, origin, relpath, ext=".html"):
        path = paths.join(origin, relpath)
        base, frag = paths.split_fragment(path)
        if base.endswith("/"):
            base += self.index_page_name
        if not base.endswith(ext):
            base += ext
        path = base + frag
        return path

    def source_path(self, path, locale=None):
        path, frag = paths.split_fragment(path)

        if (
            not path.endswith("/") and self.store.exists(path) and
            self.store.is_dir(path)
        ):
            path += "/"

        if path.endswith("/"):
            path += self.index_page_name + self.wiki_ext

        # Note that split_extension doesn't return the dot as part of the
        # extension
        basepath, ext = paths.split_extension(path)
        # If this path has no extension or has a .html extension
        if not ext or ext == "html":
            # Remove the .html extension
            if ext == "html":
                path = path[:-5]
            # Add locale specifier to page name
            if locale:
                path = "%s.%s" % (basepath, locale)
            # Add wiki source extension
            path += self.wiki_ext
        elif ext in ("txt", "jpg", "jpeg", "png", "gif", "svg", "csv", "bgeo",
                     "gz", "zip", "hda", "otl", "pic", "py", "tiff",
                     "usd", "usda", "xml"):
            pass
        elif self.store.exists(path + self.wiki_ext):
            path += self.wiki_ext

        return path

    def is_wiki(self, path):
        ext = paths.extension(path)
        return (not ext) or ext == self.wiki_ext

    def is_wiki_source(self, path):
        return paths.extension(path) == self.wiki_ext

    def is_index_page(self, path):
        assert path.startswith("/")
        dirpath, filename = paths.split_dirpath(path)
        return (filename == self.index_page_name
                or filename.startswith(self.index_page_name + "."))

    def find_source(self, path, locales=None):
        locales = locales or (None,)
        for locale in locales:
            locale = locale if locale != "en" else None
            spath = self.source_path(path, locale)
            if self.store.exists(spath):
                return spath
        return None

    def file_path(self, path):
        """
        Takes a virtual server path and translates it into a "real" file path,
        or None if the resource does not exist in a file.
        """

        return self.store.file_path(path)

    def exists(self, path):
        return self.store.exists(self.source_path(path))

    def last_modified(self, path):
        return self.store.last_modified(self.source_path(path))

    def size(self, path):
        return self.store.size(path)

    def etag(self, path, locale=None):
        spath = self.source_path(path, locale=locale)
        etag = self.store.etag(spath)
        # TODO: mix in the etags for the style and templates
        return etag
    
    def content(self, path, reformat=False, encoding="utf8"):
        text = self.store.content(path, encoding=encoding)
        if reformat:
            text = condition_string(text, add_eot=False)
        return text

    def wiki_context(self, path, conditional=True, save_to_cache=True,
                     searcher=None, profiling=False):
        m = dict(path=path, conditional=conditional,
                 save_to_cache=save_to_cache, profiling=profiling,
                 pages=self, searcher=searcher)
        m["lang"] = self.page_lang(path)
        return util.Context(m)

    def context_from(self, wcontext, path, conditional=True,
                     save_to_cache=True, searcher=None, extra_context=None):
        if wcontext is None:
            wcontext = self.wiki_context(
                path, conditional=conditional, save_to_cache=save_to_cache,
                searcher=searcher
            )
        else:
            wcontext = wcontext.push({
                "path": path,
                "pages": self,
                "searcher": searcher
            })

        if extra_context:
            wcontext.update(extra_context)

        return wcontext

    def process_indexed_doc(self, block, doc, cache):
        self._pre_pipeline.process_indexed(self, block, doc, cache)
        self._post_pipeline.process_indexed(self, block, doc, cache)

    def available_languages(self, path):
        dpath = langpaths.delang(path)
        store = self.store
        for rootpath in store.list_dir("/"):
            if langpaths.is_lang_root(rootpath):
                name = langpaths.lang_name(rootpath)
                if store.exists(langpaths.enlang(name, dpath)):
                    yield name

    def enlang(self, path, lang=None):
        if langpaths.has_lang(path):
            return path
        else:
            lang = lang or self._default_lang
            return langpaths.enlang(lang, path)

    def page_lang(self, path):
        return langpaths.lang_name(self.enlang(path))

    def _check_path(self, path, must_exist=True):
        # Translate the request path into a source path (e.g. /a/b -> /a/b.txt)
        assert paths.is_abs(path)
        path = self.source_path(path)
        if must_exist and not self.store.exists(path):
            raise stores.ResourceNotFoundError(path)
        return path

    def _check_redirect(self, path, jsondata, allow_redirect):
        # Check if the parsed page has a redirect attribute
        attrs = jsondata.get("attrs")
        if allow_redirect and attrs and "redirect" in attrs:
            url = attrs["redirect"]
            if not (url.startswith("http:") or url.startswith("https:")):
                url = self.full_path(path, url)
            raise Redirect(url)

    def parent_info_list(self, path, context, parent_getter, seen=None):
        path = self.source_path(path)
        seen = set() if seen is None else seen
        seen.add(path)

        pcache = self._parent_cache
        if path in pcache:
            return pcache[path]

        searcher = context["searcher"]
        conditional = context["conditional"]
        save_to_cache = context["save_to_cache"]

        json = self.json(path, wcontext=context, postprocess=False,
                         searcher=searcher, conditional=conditional,
                         save_to_cache=save_to_cache)
        out = [self.parent_info(path, json)]
        ppath = self.source_path(parent_getter(self, path, json))
        if path == ppath or not self.exists(ppath):
            ppath = None
        if ppath in seen:
            raise Exception("Circular parent rel: %s -> %s" % (path, ppath))

        if ppath:
            out += self.parent_info_list(ppath, context, parent_getter,
                                         seen=seen)
        self._parent_cache[path] = out
        return out

    def parent_info(self, path, json):
        # Find the subtopics section
        subtopics = copy.deepcopy(functions.subblock_by_id(json, "subtopics"))
        if subtopics:
            stbody = subtopics.get("body")
            if stbody:
                # Annotate the link to the current page
                # for item in functions.find_items(stbody, "subtopics_item"):
                #     for link in functions.find_links(item):
                #         if link.get("fullpath") == prevpath:
                #             item["is_ancestor"] = True
                #             break

                # Remove column markup
                body = functions.collapse(stbody, ("col_group", "col"))
                subtopics["body"] = body

        return {
            "path": path,
            "basepath": paths.basepath(path),
            "title": json.get("title", ()),
            "summary": json.get("summary", ()),
            "attrs": json.get("attrs", {}),
            "subtopics": subtopics,
        }

    def json(self, path, wcontext=None, conditional=True, process=True,
             postprocess=True, save_to_cache=True, extra_context=None,
             searcher=None, allow_redirect=False):
        # t1 = time.time()
        path = self._check_path(path)

        # Create a wiki context for passing information down to processors
        wcontext = self.context_from(wcontext, path=path,
                                     conditional=conditional,
                                     save_to_cache=save_to_cache,
                                     searcher=searcher,
                                     extra_context=extra_context)
        jsondata = None
        from_cache = False

        # Try to get the JSON data from the cache
        if wcontext.get("conditional") and self.cache:
            jsondata = self.cache.get_cached_json(self, path)

        # If the file wasn't cached, load and parse it
        if jsondata is None:
            source = self.content(path)
            jsondata = parse_to_root(source)

            # Run pre-processors
            if process:
                self._pre_pipeline.apply(jsondata, wcontext)

            # If we're caching, save the parsed JSON to a file in the cache.
            if self.cache and save_to_cache:
                self.cache.put_cache(path, jsondata)
        else:
            from_cache = True

        jsondata["from_cache"] = from_cache
        if process and postprocess:
            self._post_pipeline.apply(jsondata, wcontext, profile=False)

        self._check_redirect(path, jsondata, allow_redirect)
        # print(".. Total", time.time() - t1, path)
        return jsondata

    def string_to_json(self, path, content, wcontext=None, searcher=None,
                       extras=None, postprocess=True, allow_redirect=False):
        path = self._check_path(path, must_exist=False)

        # Create a wiki context for passing information down to processors
        wcontext = self.context_from(wcontext, path=path, conditional=False,
                                     save_to_cache=False, searcher=searcher,
                                     extra_context=extras)

        jsondata = parse_to_root(content)
        self._pre_pipeline.apply(jsondata, wcontext)

        if postprocess:
            self._post_pipeline.apply(jsondata, wcontext)

        self._check_redirect(path, jsondata, allow_redirect)
        return jsondata

    def _get_template(self, templatename):
        try:
            return self.jinja_env.get_template(templatename)
        except stores.ResourceNotFoundError:
            return Exception("Template not found: %r" % templatename)

    def json_to_html(self, path, jsondata, stylename=None, templatename=None,
                     extras=None, searcher=None):
        basepath = paths.basepath(path)

        kwargs = {
            "path": path,
            "basepath": basepath,
            "is_index_page": self.is_index_page(path),
            "rel": util.make_rel_fn(path, self.index_page_name, self.store),
            "searcher": searcher,
            "pages": self,
            "paths": paths,
        }
        if extras:
            kwargs.update(extras)

        stylename = stylename or self._default_style
        styleobj = self.style(stylename)
        stylectx, render = styleobj.context_and_function(path, jsondata, kwargs)

        # Create a function to apply the stylesheet to a given object
        def render_styles(obj):
            return render(stylectx, obj)

        templatename = templatename or self._default_template
        template = self._get_template(templatename)

        return template.render(docroot=jsondata, render_styles=render_styles,
                               functions=functions, **kwargs)

    def html(self, path, stylename=None, templatename=None, language=None,
             conditional=True, save_to_cache=True, searcher=None, extras=None,
             allow_redirect=False):
        jsondata = self.json(path, conditional=conditional,
                             save_to_cache=save_to_cache, searcher=searcher,
                             allow_redirect=allow_redirect)

        return self.json_to_html(path, jsondata, stylename=stylename,
                                 templatename=templatename, extras=extras,
                                 searcher=searcher)

    def render_template(self, template_path, **kwargs):
        assert self.jinja_env.loader.store() is self.store
        template = self.jinja_env.get_template(template_path)
        return template.render(kwargs)

    def preview(self, path, content, stylename=None, templatename=None,
                language=None, searcher=None, extras=None):
        extras = extras or {}
        extras["preview"] = True

        jsondata = self.string_to_json(path, content, searcher=searcher,
                                       extras=extras)
        return self.json_to_html(path, jsondata, stylename=stylename,
                                 templatename=templatename, extras=extras,
                                 searcher=searcher)


