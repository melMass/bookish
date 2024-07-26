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

from __future__ import print_function
import os
import datetime
import mimetypes
import sys
import threading
import time
import traceback

import flask

import werkzeug.exceptions

from bookish import compat, paths, i18n, stores, util
from bookish.edit.checkpoints import Checkpoints
from bookish.wiki import langpaths, wikipages


bookishapp = flask.Flask(__name__, static_folder=None, static_url_path=None)
# bookishapp = Blueprint('bookish_app', __name__)

extra_types = {
    "bkgrammar": "text/plain",
}

indexing_thread = threading.Thread()


ICONS_PATH = "/icons/"


@bookishapp.after_request
def after_request(response):
    response.headers.add('Accept-Ranges', 'bytes')
    return response


def send_file_partial(path, conditional):
    """
    Simple wrapper around send_file which handles HTTP 206 Partial Content
    (byte ranges)
    TODO: handle all send_file args, mirror send_file's error handling
    (if it has any)
    """

    byterange = flask.request.range
    if not byterange:
        return flask.send_file(path, conditional=conditional)

    size = os.path.getsize(path)
    mimetype = mimetypes.guess_type(path)[0]
    with open(path, 'rb') as f:
        return send_fileobj_partial(f, size, mimetype, conditional)


def send_fileobj_partial(f, size, mimetype, conditional):
    byterange = flask.request.range
    if not byterange:
        return flask.send_file(f, conditional=conditional, mimetype=mimetype)

    import zipfile

    start, end = byterange.range_for_length(size)
    f.seek(start)
    data = f.read(end - start)

    rv = flask.Response(data, 206, mimetype=mimetype, direct_passthrough=True)
    rv.content_range = byterange.make_content_range(size)
    return rv


def null_rel(x):
    return x


class NotModified(werkzeug.exceptions.HTTPException):
    """
    An HTTP "304 Not Modified" response.
    """

    code = 304

    def get_response(self, environment):
        return flask.Response(status=304)


def is_unconditional():
    """
    Returns True if the given flask request is unconditional (that is, cannot
    be served from a cache).
    """

    headers = flask.request.headers
    return (headers.get("Pragma") == "no-cache"
            or headers.get("Cache-Control") == "no-cache")


def directory_list(pages, dirpath):
    store = pages.store
    names = store.list_dir(dirpath)
    files = []

    for name in names:
        path = paths.join(dirpath, name)
        link = path
        if pages.is_wiki(link):
            link = paths.basepath(link)
        isdir = store.is_dir(path)
        if isdir:
            size = -1
            mod = -1
        else:
            size = store.size(path)
            mod = store.last_modified(path)

        files.append({
            "path": path,
            "link": link,
            "name": name,
            "ext": paths.extension(name),
            "isdir": isdir,
            "size": size,
            "modified": mod,
        })

    return files


def directory_page(pages, dirpath):
    """
    Renders a simple template to show the files in a directory.
    """

    pages = get_wikipages()
    files = directory_list(pages, dirpath)
    return pages.render_template("dir.jinja2", path=dirpath, files=files)


def get_request_language(pages, path):
    """
    Get the human language from a flask request
    """

    if flask.request.get("hl"):
        return flask.request.get("hl")

    if flask.session:
        hl = flask.session.get("i18n_language")
        if hl:
            return hl

    header_string = flask.request.headers.get("accept-languages")
    available_langs = pages.available_langauges(path)
    return i18n.parse_http_accept_language(header_string, available_langs)


def get_request_userid():
    return "_"


# Error handlers

@bookishapp.errorhandler(404)
def page_not_found(exception):
    path = flask.request.path
    config = flask.current_app.config

    pages = get_wikipages()
    store = pages.store

    editable = False
    isdir = store.exists(path) and store.is_dir(path)
    if config.get("EDITABLE") and not isdir:
        editable = pages.is_wiki(path)

    content = pages.render_template('404.jinja2', path=path, editable=editable,
                                    rel=null_rel, num=404)
    return content, 404


@bookishapp.errorhandler(500)
def internal_error(exception):
    from bookish.coloring import format_string

    path = flask.request.path

    pages = get_wikipages()
    trace = traceback.format_exc()
    trace = format_string(trace, "pytb")

    content = pages.render_template('500.jinja2', path=path, trace=trace,
                                    rel=null_rel, num=500)
    return content, 500


# Endpoints

@bookishapp.route('/', defaults={'path': ''})
@bookishapp.route("/<path:path>")
def show(path):
    request = flask.request
    config = flask.current_app.config

    pages = get_wikipages()
    editable = config["EDITABLE"]

    store = pages.store
    path = paths.normalize("/" + path)
    pathexists = store.exists(path)
    spath = pages.source_path(path)
    cond = not is_unconditional()
    isdir = pathexists and store.is_dir(path)

    if isdir:
        if not path.endswith("/"):
            return flask.redirect(path + "/", 302)
        if not store.exists(spath):
            return directory_page(pages, path)

    rpath = store.redirect(spath)
    if rpath is not None:
        # rpath = paths.basepath(rpath)
        return flask.redirect(rpath, 302)

    if pathexists and not isdir:
        fpath = store.file_path(path)
        if fpath:
            return send_file_partial(fpath, cond)
        else:
            try:
                size = store.size(path)
                mimetype, encoding = mimetypes.guess_type(path)
                f = pages.store.open(path)
                if hasattr(f, "name"):
                    f.name = None
                resp = send_fileobj_partial(f, size, mimetype, cond)
                etag = "%s.%s" % (path, str(store.last_modified(path)))
                resp.set_etag(etag)
                return resp
            except stores.ResourceNotFoundError:
                raise werkzeug.exceptions.NotFound

    elif store.exists(spath):
        pagelang = pages.page_lang(path)
        etag = pages.etag(spath)
        if cond and etag:
            if etag in request.if_none_match:
                raise NotModified()

        try:
            indexer = pages.indexer()
            searcher = None
            if request.args.get("searcher") != "no":
                searcher = indexer.searcher()

            if request.args.get("format") == "simple":
                templatepath = "/templates/plain.jinja2"
                stylespath = "/templates/tooltip.jinja2"
            else:
                templatepath = request.args.get("template")
                stylespath = request.args.get("styles")

            extras = {
                "editable": editable,
                "q": request.args.get('q', ''),
                "pagelang": pagelang,
            }

            # NOTE: redirection is NOT actually handled here currently. Instead
            # the template adds a <meta> tag to do the redirection, so it works
            # on the website.
            try:
                html = pages.html(path, conditional=cond, searcher=searcher,
                                  extras=extras, allow_redirect=False,
                                  templatename=templatepath,
                                  stylename=stylespath)
            except wikipages.Redirect as e:
                return flask.redirect(e.newpath, 302)

            resp = flask.Response(html)
            if etag:
                resp.set_etag(etag)
            return resp

        except stores.ResourceNotFoundError:
            e = sys.exc_info()[1]
            flask.current_app.logger.error(e)
            raise werkzeug.exceptions.NotFound
    else:
        raise werkzeug.exceptions.NotFound(path)


@bookishapp.route("/allicons")
def icon_list():
    request = flask.request

    pages = get_wikipages()
    store = pages.store
    dirs = {}
    for dirname in store.list_dir(ICONS_PATH):
        dirpath = paths.join(ICONS_PATH, dirname)
        if store.is_dir(dirpath):
            svgs = []
            for filename in store.list_dir(dirpath):
                name, ext = paths.split_extension(filename)
                if ext == "svg":
                    svgs.append(name)
            if svgs:
                dirs[dirname] = svgs

    rel = util.make_rel_fn("/allicons", pages.index_page_name)
    fixed = request.args.get("fixed")
    dark = request.args.get("dark")
    return pages.render_template("icons_dir.jinja2", base=ICONS_PATH, dirs=dirs,
                                 rel=rel, fixed=fixed, dark=dark)


@bookishapp.route("/_search")
def search_page():
    request = flask.request
    config = flask.current_app.config
    resp_type = request.args.get("type", "html")

    pages = get_wikipages()
    indexer = pages.indexer()
    searcher = indexer.searcher()
    qobj = searcher.query()
    style = pages.style("simple_wiki.jinja2")

    def render_instant(json):
        return style.render("/_search", json)

    cat_order = config.get("CATEGORIES", "").split()

    shortcuts = list(config.get("SHORTCUTS", ()))
    shortcuts.extend(config.get("EXTRA_SHORTCUTS", ()))

    qstring = request.args.get("q", "")
    permanent = request.args.get("permanent") == "true"
    # startpos = request.args.get("startpos", "")
    # endpos = request.args.get("endpos", "")
    category = request.args.get("category")
    require = request.args.get("require")
    pagelang = request.args.get("lang")
    sequence = int(request.args.get("sequence", "0"))
    templatepath = request.args.get("template", config["SEARCH_TEMPLATE"])

    r = qobj.results(pages, qstring, cat_order, category=category,
                     require=require, shortcuts=shortcuts, lang=pagelang,
                     sequence=sequence)
    if resp_type == "json":
        return flask.jsonify(r)

    resp = pages.render_template(templatepath, permanent=permanent, paths=paths,
                                 render_instant=render_instant, **r)
    # resp.headers['X-Request-Number'] = str(requestnum)
    return resp


@bookishapp.route("/_field/<name>")
def field_contents(name):
    pages = get_wikipages()
    indexer = pages.indexer()
    searcher = indexer.searcher()
    terms = []
    for x in searcher.searcher.reader().field_terms(name):
        terms.append("<li>%s</li>" % repr(x))
    return "".join(terms)


@bookishapp.route("/_toc/<path:path>")
def toc_page(path):
    from bookish import functions

    request = flask.request
    pages = get_wikipages()
    indexer = pages.indexer()
    searcher = indexer.searcher()

    path = "/" + path
    ext = paths.extension(path)
    pagepath = paths.strip_extension(path)
    basepath = request.args.get("base", path)
    template = request.args.get("template", "plain.jinja2")

    spath = pages.source_path(pagepath)
    if pages.exists(spath):
        json = pages.json(spath, searcher=searcher)
        subtopics = functions.subblock_by_id(json, "subtopics")
        sublist = subtopics.get("body", ()) if subtopics else ()

        if ext == ".json":
            return flask.jsonify(sublist)
        elif ext == ".html":
            html = pages.json_to_html(basepath, sublist,
                                      templatename=template)
            return html
        else:
            raise Exception("Don't know extension %r" % ext)

    else:
        raise werkzeug.exceptions.NotFound


@bookishapp.route("/_dir")
def list_dir():
    request = flask.request
    pages = get_wikipages()
    dirpath = request.args.get("path", "/")

    if not dirpath.endswith("/"):
        dirpath += "/"

    if pages.store.exists(dirpath) and pages.store.is_dir(dirpath):
        files = directory_list(pages, dirpath)

        for file in files:
            d = file.get("modified")
            if d and isinstance(d, datetime.datetime):
                file["modified"] = time.mktime(d.timetuple())

        return flask.jsonify({
            "files": files,
        })

    raise werkzeug.exceptions.NotFound


@bookishapp.route("/_edit/<path:path>")
def edit_wiki(path):
    config = flask.current_app.config
    pages = get_wikipages()

    # editable = config["EDITABLE"]
    # if not editable:
    #     flask.abort(500)

    path = paths.normalize("/" + path)
    path = pages.source_path(path)
    if paths.extension(path) != config["WIKI_EXT"]:
        # TODO: better error here!
        flask.abort(500)

    userid = get_request_userid()
    cp = Checkpoints(userid, pages.store, pages.cache_store())

    from_autosave = False
    if pages.exists(path):
        lastmod = pages.last_modified(path)
        if cp.has_autosave_after(path, lastmod):
            source = cp.get_autosave(path)
            from_autosave = True
        else:
            source = pages.content(path, reformat=True)
    else:
        lastmod = 0
        source = ""

    return pages.render_template("edit.jinja2", source=source, path=path,
                                 rel=null_rel, lastmod=lastmod,
                                 from_autosave=from_autosave)


@bookishapp.route("/_preview/", methods=["GET", "PUT"])
def preview_wiki():
    request = flask.request
    config = flask.current_app.config

    pages = get_wikipages()
    indexer = pages.indexer()
    searcher = indexer.searcher()
    autosave_seconds = config.get("AUTOSAVE_SECONDS", 10)
    autosave = (
        config.get("AUTOSAVE", True) and request.form.get("autosave") != "false"
    )

    assert "path" in request.form
    path = request.form["path"]
    assert path
    source = request.form.get("source", "")
    scrollTop = int(request.form.get("scrollTop") or "0")

    lastmod = 0
    if pages.exists(path):
        lastmod = pages.last_modified(path)

    last_autosave = 0
    if autosave:
        session = flask.session
        userid = get_request_userid()

        if "last_autosave" in session:
            last_autosave = session.get("last_autosave")
        else:
            last_autosave = datetime.datetime.utcnow()

        edit_store = stores.store_from_spec(config.get("EDIT_STORE"))
        cp = Checkpoints(userid, edit_store, pages.cachestore)
        now = datetime.datetime.utcnow()
        if now - last_autosave >= datetime.timedelta(seconds=autosave_seconds):
            cp.autosave(path, source)
            last_autosave = session["last_autosave"] = now

    extras = {"rel": util.make_rel_fn(path, pages.index_page_name)}

    html = pages.preview(path, source, searcher=searcher, extras=extras,
                         templatename="/templates/preview.jinja2")
    return flask.jsonify(html=html, last_modified=lastmod,
                         last_autosave=last_autosave, scrollTop=scrollTop)


@bookishapp.route("/_load/", methods=["GET"])
def load_wiki():
    request = flask.request
    config = flask.current_app.config
    pages = get_wikipages()
    edit_store = stores.store_from_spec(config.get("EDIT_STORE"))
    path = request.args["path"]

    exists = pages.store.exists(path)
    if exists:
        source = pages.content(path, reformat=True)
    else:
        source = ""

    cp = Checkpoints(get_request_userid(), edit_store, pages.cachestore)
    if exists and cp.has_autosave_after(path, pages.last_modified(path)):
        has_autosave = True
        autosave = cp.get_autosave(path)
    else:
        has_autosave = False
        autosave = None

    return flask.jsonify(exists=exists, source=source,
                         has_autosave=has_autosave, autosave=autosave)


@bookishapp.route("/_wiki_templates/", methods=["GET"])
def list_wiki_forms():
    request = flask.request
    config = flask.current_app.config
    pages = get_wikipages()
    path = request.form["path"]

    store = pages.store
    tpath = config.get("WIKI_TEMPLATES")
    if tpath and store.exists(tpath) and store.is_dir(tpath):
        filepaths = store.list_dir(tpath)


@bookishapp.route("/_save/", methods=["PUT"])
def save_wiki():
    request = flask.request
    config = flask.current_app.config
    maxnum = config.get("CHECKPOINT_MAX", 10)

    pages = get_wikipages()
    path = request.form["path"]
    source = request.form["source"]
    # encoding = request.form.get("encoding", "utf8")

    edit_store = stores.store_from_spec(config.get("EDIT_STORE"))
    userid = get_request_userid()
    cp = Checkpoints(userid, edit_store, pages.cachestore, maxnum)
    cp.save_checkpoint(path, source, encoding="utf8")
    return source


@bookishapp.route("/_make_dir/", methods=["PUT"])
def new_dir():
    request = flask.request
    config = flask.current_app.config
    path = request.form["path"]

    edit_store = stores.store_from_spec(config.get("EDIT_STORE"))
    if edit_store.writable(path):
        edit_store.make_dir(path)
        return '', 204

    flask.abort(500)


@bookishapp.route("/_move/", methods=["PUT"])
def move_wiki():
    request = flask.request
    config = flask.current_app.config
    maxnum = config.get("CHECKPOINT_MAX", 10)

    pages = get_wikipages()
    path = request.form["path"]
    newpath = request.form["newpath"]

    edit_store = stores.store_from_spec(config.get("EDIT_STORE"))
    userid = get_request_userid()
    cp = Checkpoints(userid, edit_store, pages.cachestore, maxnum)
    if edit_store.writable(newpath):
        edit_store.move(path, newpath)
        cp.move_checkpoints(path, newpath)
        return '', 204

    flask.abort(500)


@bookishapp.route("/_delete/", methods=["PUT"])
def delete_wiki():
    request = flask.request
    config = flask.current_app.config
    path = request.form["path"]

    edit_store = stores.store_from_spec(config.get("EDIT_STORE"))
    if edit_store.writable(path):
        pages = get_wikipages()
        maxnum = config.get("CHECKPOINT_MAX", 10)
        edit_store.delete(path)
        cp = Checkpoints(get_request_userid(), edit_store, pages.cachestore,
                         maxnum)
        cp.delete_checkpoints(path)
        return '', 204

    flask.abort(500)


@bookishapp.route("/_list_checkpoints/", methods=["GET"])
def list_checkpoints():
    request = flask.request
    config = flask.current_app.config
    pages = get_wikipages()
    maxnum = config.get("CHECKPOINT_MAX", 10)
    path = request.args["path"]

    edit_store = stores.store_from_spec(config.get("EDIT_STORE"))
    cp = Checkpoints(get_request_userid(), edit_store, pages.cachestore, maxnum)
    return flask.jsonify({
        "checkpoints": cp.checkpoints(path)
    })


@bookishapp.route("/_load_checkpoint/", methods=["GET"])
def load_checkpoint():
    request = flask.request
    config = flask.current_app.config
    pages = get_wikipages()
    path = request.args["path"]
    cpid = request.args["id"]

    edit_store = stores.store_from_spec(config.get("EDIT_STORE"))
    userid = get_request_userid()
    cp = Checkpoints(userid, edit_store, pages.cachestore)
    return cp.load_checkpoint(path, cpid, encoding="utf8")


@bookishapp.route("/_tooltip/<path:path>")
def debug_tooltip(path):
    pages = get_wikipages()
    indexer = pages.indexer()
    searcher = indexer.searcher()

    path = paths.normalize("/" + path)
    path = pages.source_path(path)

    html = pages.html(
        path, templatename="/templates/plain.jinja2",
        stylesname="/templates/tooltip.jinja2",
        conditional=False, searcher=searcher,
    )
    return html


# @bookishapp.route("/_headers")
# def show_headers():
#     out = "<table>"
#     for key, value in flask.request.headers:
#         out += "<tr><td>%s</td><td>%s</td><tr>" % (key, value)
#     out += "</table>"
#     return out


@bookishapp.route("/_wiki/<path:path>")
def debug_wiki_structure(path):
    pages = get_wikipages()
    indexer = pages.indexer()
    searcher = indexer.searcher()

    path = paths.normalize("/" + path)
    path = pages.source_path(path)
    process = flask.request.args.get("process") != "false"

    jsondata = pages.json(paths.basepath(path), conditional=False,
                          extra_context=flask.request.args, searcher=searcher,
                          process=process)
    return pages.render_template("debug_wiki.jinja2", path=path, root=jsondata,
                                 searcher=searcher)


@bookishapp.route("/_indexed/<path:path>")
def debug_search(path):
    pages = get_wikipages()
    indexer = pages.indexer()
    sables = indexer.searchables

    path = paths.normalize("/" + path)
    path = pages.source_path(path)

    jsondata = pages.json(path, conditional=False, postprocess=False)
    docs = list(sables.documents(pages, path, jsondata, flask.request.args, {}))
    return pages.render_template("debug_search.jinja2", path=path, docs=docs)


@bookishapp.route("/_reindex", methods=("GET", "PUT"))
def update_index():
    request = flask.request

    if request.method == "GET":
        return """
        <form method='post'>
        <input type='submit' value='Reindex'>
        <input type='checkbox' id="clean" name='clean' value='true'>
        <label for="clean">Clean</label>
        </form>
        """
    elif request.method == "PUT":
        pages = get_wikipages()
        indexer = pages.indexer()
        clean = request.form.get("clean") == "true"
        indexer.update(pages, clean=clean)
        return flask.redirect("/_reindex")


@bookishapp.route("/_text/<path:path>")
def debug_textify(path):
    pages = get_wikipages()
    indexer = pages.indexer()

    searcher = None
    if flask.request.args.get("searcher") != "no":
        searcher = indexer.searcher()

    path = paths.normalize("/" + path)
    path = pages.source_path(path)

    jsondata = pages.json(path, searcher=searcher, conditional=False)
    output = pages.textify(jsondata)
    return flask.Response(output, mimetype="text/plain")


@bookishapp.route("/_load_example", methods=['PUT'])
def load_example():
    """This is an extremelly dangerous function so security is of the utmost
    importance."""
    request = flask.request
    if request.method == "PUT":
        from houdinihelp.api import load_example

        url = request.form.get("url")
        launch = request.form.get("launch") == "true"
        load_example(url, launch)
        return "Success", 200

    flask.abort(400)


# Create useful objects based on the current app

def get_store(app=None):
    app = app or flask.current_app
    with app.app_context():
        return wikipages.store_from_config(app.config)


def get_wikipages(app=None):
    from houdinihelp import hpages

    app = app or flask.current_app
    with app.app_context():
        return hpages.pages_from_config(app.config, logger=app.logger)




