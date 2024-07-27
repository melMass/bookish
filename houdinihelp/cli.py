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

from __future__ import print_function
import os.path
import errno
import shutil
import sys

import click

from bookish import paths, util
from bookish.stores import expandpath

from houdinihelp import hconfig, hpages


# Helper functions

def _mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno != errno.EEXIST or not os.path.isdir(path):
            raise


def _parse_vars(strings):
    d = {}
    for string in strings:
        name, value = string.split("=", 1)
        d[name] = value
    return d


def _archive_tree(dirpath, zfile, force, include, exclude):
    import zipfile

    dirpath = expandpath(dirpath)
    filepaths = list(util.file_paths(dirpath, include, exclude))
    t = util.perf_counter()

    if os.path.exists(zfile):
        uptodate = True
        ztime = os.path.getmtime(zfile)
        # print("Zip file mod time=", ztime)
        for p in filepaths:
            ptime = os.path.getmtime(p)
            # print(p, ptime, ptime > ztime)
            if ptime > ztime:
                uptodate = False
                break

        if uptodate:
            # print("%s is up to date" % zfile)
            return

    count = 0

    # Ensure the destination directory exists.
    dest_dir = os.path.dirname(zfile)
    _mkdir_p(dest_dir)

    print("Archiving", dirpath, "to", zfile)
    zf = zipfile.ZipFile(zfile, "w", compression=zipfile.ZIP_DEFLATED)
    for path in filepaths:
        rp = os.path.relpath(path, dirpath).replace("\\", "/")
        zf.write(path, arcname=rp)
        count += 1

    print("Archived %s files in %.01f sec" % (count, util.perf_counter() - t))
    zf.close()


def _copy_file(srcpath, destpath, force, logger=None):
    if (
        force
        or not os.path.exists(destpath)
        or os.path.getmtime(srcpath) > os.path.getmtime(destpath)
    ):
        parent = os.path.dirname(destpath)
        _mkdir_p(parent)
        # print("Copying %s to %s" % (srcpath, destpath))
        shutil.copy2(srcpath, destpath)
        return True


def _copy_tree(srcdir, destdir, force=False, include=None, exclude=None):
    count = 0
    for srcpath in util.file_paths(srcdir, include, exclude):
        relpath = os.path.relpath(srcpath, srcdir)
        destpath = os.path.join(destdir, relpath)
        if _copy_file(srcpath, destpath, force):
            count += 1
    return count


class Dots(object):
    def __init__(self, width=72):
        self.count = 0
        self.width = width

    def dot(self):
        self.count += 1
        print(".", end="\n" if not self.count % self.width else "")


# Group

# def get_config(ctx, scriptinfo):
#     from houdinihelp.server import get_houdini_app
# 
#     params = ctx.find_root().params
# 
#     # For build steps that can run before hou is built, prevent the hou module
#     # from being loaded on subsequent incremental builds to avoid potential
#     # errors on Windows if a library is being built at the same time.
#     if params["disablehou"]:
#         import sys
#         sys.modules['hou'] = None
# 
#     return get_houdini_app(
#         config_file=params["config"],
#         config_obj=params["object"],
#         logfile=params["logfile"],
#         loglevel=params["loglevel"],
#         debug=params["debug"],
#     )


@click.group()
@click.option("-C", "--config", type=str)
@click.option("-l", "--logfile", type=click.Path())
@click.option("-L", "--loglevel", type=str)
@click.option("-d", "--debug", is_flag=True)
@click.option("--disablehou", is_flag=True)
@click.pass_context
def cli(ctx, config, logfile, loglevel, debug, disablehou):
    """Command line tool for running Houdini help tasks."""

    if disablehou:
        import sys
        sys.modules["hou"] = None

    cfg = hconfig.read_houdini_config(config_file=config,
                                      root_path=os.getcwd(),
                                      use_houdini_path=not disablehou)

    if logfile:
        cfg["LOGFILE"] = logfile
    if loglevel:
        cfg["LOGLEVEL"] = loglevel
    if debug is not None:
        cfg["DEBUG"] = debug

    ctx.obj = hpages.pages_from_config(cfg)


# Commands

@cli.command()
@click.pass_obj
def clear_cache(pages):
    """Clears all files from the wiki JSON cache."""

    pages.cache.empty()


@cli.command()
@click.option("-h", "--host", default="0.0.0.0")
@click.option("-p", "--port", type=int, default=8080)
@click.option("--debug", is_flag=True, default=False)
@click.option("--vars", "vars_", type=str, default=None)
@click.option("--bgindex", type=bool, default=None)
@click.pass_obj
def serve(pages, host, port, debug, vars_, bgindex):
    """Starts a serving help pages over HTTP."""

    from houdinihelp.server import start_server

    cfg = pages.config
    if vars_:
        cfg.update(_parse_vars(vars_))
    if bgindex is not None:
        cfg["ENABLE_BACKGROUND_INDEXING"] = bgindex

    start_server(host, port, override_config=cfg, debug=debug)


@cli.command()
@click.argument("path", type=str, required=True)
@click.pass_obj
def html(pages, path):
    """Outputs the rendered HTML for a wiki path."""

    print(pages.html(path))


@cli.command()
@click.option("--images/--noimages", "images", default=True)
@click.option("--links/--nolinks", "links", default=True)
@click.pass_obj
def missing(pages, images, links):
    """Generates a list of broken links and unused images."""

    from bookish.testing import find_missing

    print("Reading pages")
    t = util.perf_counter()
    misses, unused_images = find_missing(pages, images, links)

    if images or links:
        print("\nBROKEN LINKS")
        last_path = None
        for path, value, linkpath in misses:
            if path != last_path:
                print(path + ":")
                last_path = path
            print("    %s (%s)" % (value, linkpath))

    print("\nUNUSED IMAGES")
    for imgpath in sorted(unused_images):
        print(imgpath)


@cli.command()
@click.argument("dirpath", type=click.Path(exists=True, file_okay=False),
                required=False)
@click.option("-p", "--prefix", type=str, default="/")
@click.option("--cache/--no-cache", default=True)
@click.option("-v", "--var", "vars_", multiple=True)
@click.option("-j", "--procs", type=int, default=1)
@click.option("--no-output", type=bool, default=False)
@click.pass_obj
def generate(pages, dirpath, prefix, cache, vars_, procs, no_output):
    """Generates HTML for a tree of wiki pages into a directory."""

    pages.config.update(_parse_vars(vars_))
    print("Building path list")
    pathlist = sorted(p for p in util.get_prefixed_paths(pages, prefix)
                      if pages.is_wiki_source(p) and pages.exists(p))
    t = util.perf_counter()

    if procs == 1:
        from bookish.wiki.wikipages import write_html_output
        indexer = pages.indexer()
        searcher = indexer.searcher()
        for path in pathlist:
            print("Generating", path)
            write_html_output(pages, path, dirpath, cache=cache,
                              searcher=searcher)
    else:
        from bookish.wiki.wikipages import write_html_output_multi
        write_html_output_multi(pages, dirpath, procs, pathlist)

    print("Total time", util.perf_counter() - t)


@cli.command(name="index")
@click.option("--clean", is_flag=True)
@click.option("--optimize", is_flag=True)
@click.option("--touchfile", type=click.Path(dir_okay=False, writable=True),
              default=None)
@click.pass_obj
def reindex(pages, clean, optimize, touchfile):
    """Updates the full text index."""

    indexer = pages.indexer()
    changed = indexer.update(pages, clean=clean, optimize=optimize)
    if changed:
        print("Index updated")
        if touchfile:
            with open(touchfile, "w"):
                os.utime(touchfile, None)
    else:
        print("Nothing to do")


@cli.command()
@click.argument("query", nargs=-1)
@click.option("-l", "--limit", type=int, default=0)
@click.pass_obj
def search(pages, query, limit=None, stored=False):
    """Prints the result of a search query."""

    indexer = pages.indexer()

    q = indexer.query()
    q.set(" ".join(query))

    if limit:
        q.set_limit(int(limit))

    import pprint
    for hit in q.search():
        if stored:
            pprint.pprint(dict(hit))
        else:
            print(hit["path"], hit["title"])


@cli.command()
@click.argument("prefix", required=True)
@click.option("--width", type=int, default=72)
@click.option("-o", "--outfile", type=click.Path(dir_okay=False, writable=True))
@click.option("-f", "--force", is_flag=True)
@click.pass_obj
def textify(pages, prefix, width, outfile, force):
    """Prints the textified version of a wiki page or tree of wiki pages."""

    from datetime import datetime
    import random

    store = pages.store
    logger = pages.logger
    indexer = pages.indexer()
    searcher = indexer.searcher()
    # textifier_class = pages.textifier()

    all_paths = list(util.get_prefixed_paths(pages, prefix))
    # Check if we can skip generating the file if the existing
    if outfile and os.path.exists(outfile) and not force:
        outtime = datetime.utcfromtimestamp(os.path.getmtime(outfile))
        uptodate = True
        for path in all_paths:
            lastmod = store.last_modified(path)
            if lastmod > outtime:
                logger.info("%s (%s) is out of date compared to %s (%s)",
                            outfile, outtime, path, lastmod)
                uptodate = False
                break
        if uptodate:
            logger.info("%s is up to date", outfile)
            return

    tt = util.perf_counter()
    if outfile:
        tempname = outfile + "." + str(random.randint(1, 100000))
        stream = open(tempname, "wb")
    else:
        stream = sys.stdout

    for path in all_paths:
        if pages.is_wiki_source(path):
            logger.debug("Textifying %s", path)
            jsondata = pages.json(path, searcher=searcher)
            logger.debug("from_cache=%s", jsondata.get("from_cache"))

            t = util.perf_counter()
            output = pages.textify(jsondata, path=path)
            logger.debug("Textifying took %0.04f", util.perf_counter() - t)

            stream.write(output.encode("utf-8"))
            stream.write(b"\n")

    if outfile:
        stream.close()
        shutil.move(tempname, outfile)
        tt = util.perf_counter() - tt
        logger.info("Textifying %s took %f s", outfile, tt)


@cli.command()
@click.argument("dirpath", type=click.Path(exists=True, file_okay=False),
                required=True)
@click.argument("zipfile", type=click.Path(dir_okay=False, writable=True),
                required=True)
@click.option("-f", "--force", is_flag=True)
@click.option("--include", type=str)
@click.option("--exclude", type=str)
def archive(dirpath, zipfile, force, include, exclude):
    """Builds a zip archive."""

    # Delegate to a helper function, because copy_help needs to call it too, and
    # click doesn't like anyone else calling functions marked as commands
    _archive_tree(dirpath, zipfile, force, include, exclude)


@cli.command()
@click.argument("srcdir", type=click.Path(exists=True, file_okay=False),
                required=True)
@click.argument("destdir", type=click.Path(exists=True, file_okay=False),
                required=True)
@click.option("--force", is_flag=True)
@click.option("--zipdirs", type=click.Path(exists=True, dir_okay=False,
                                           readable=True))
@click.option("--include", type=str)
@click.option("--exclude", type=str)
def copy_help(srcdir, destdir, force, zipdirs, include, exclude):
    """Copies and archives help sources into the install dir."""

    srcdir = expandpath(srcdir)
    destdir = expandpath(destdir)

    print("Copying help from %s to %s" % (srcdir, destdir))
    t = util.perf_counter()
    zipset = set()
    if zipdirs:
        zipdirfile = expandpath(zipdirs)
        with open(zipdirfile) as f:
            zipset = set(line.strip() for line in f)

    # Iterate over the top-level items in the srcdir. If it's a directory,
    # check if it should be zipped. If it should, archive it, if not use
    # _copy_tree. If it's a file, use _copy_file.
    for name in os.listdir(srcdir):
        if name.startswith("."):
            continue

        srcpath = os.path.join(srcdir, name)
        destpath = os.path.join(destdir, name)
        if os.path.isdir(srcpath):
            if name in zipset:
                zfile = destpath + ".zip"
                _archive_tree(srcpath, zfile, force, include, exclude)
            else:
                _copy_tree(srcpath, destpath, force, include, exclude)
        else:
            _copy_file(srcpath, destpath, force)

    print("Copied help in %.01f sec" % (util.perf_counter() - t,))


@cli.command()
@click.option("--file", "filepath", default=None,
              type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option("--dir", "dirpath", default=None,
              type=click.Path(exists=True, file_okay=False))
@click.option("--meta", is_flag=True)
def grammar(filepath, dirpath, meta):
    """Generates a Python module from a Bookish grammar file."""

    import os.path
    from bookish.parser.builder import build_meta, Builder

    if filepath:
        todo = [filepath]
    elif dirpath:
        todo = [name for name in os.listdir(dirpath)
                if name.endswith(".bkgrammar")]
    else:
        print("No grammars to compile")
        return

    for path in todo:
        path = os.path.abspath(path)
        dirpath, filepart = os.path.split(path)
        basename, ext = os.path.splitext(filepart)
        outpath = os.path.join(dirpath, basename + ".py")

        print("Compiling grammar in", path, "to", outpath)
        with open(path) as f:
            gstring = f.read()
        with open(outpath, "w") as o:
            if meta or basename == "meta":
                build_meta(gstring, o)
            else:
                Builder(file=o).build_string(gstring)


@cli.command()
@click.option("--prefix", type=str, default="/")
@click.option("-t", "--top", type=int, default=10)
@click.pass_obj
def profile(pages, prefix, top):
    """Tests the parsing time of every wiki pages in a tree."""

    indexer = pages.indexer()
    searcher = indexer.searcher()
    t = util.perf_counter()

    print("Parsing all pages")
    times = []
    for path in util.get_prefixed_paths(pages, prefix):
        if not pages.is_wiki_source(path):
            continue

        tt = util.perf_counter()
        _ = pages.json(path, searcher=searcher, conditional=False,
                       save_to_cache=False)
        secs = util.perf_counter() - tt
        times.append((secs, path))
        print(path, secs)
    times.sort(reverse=True)

    print("\nTotal time", util.perf_counter() - t)
    if top:
        print("TOP", top, "SLOWEST")
        for secs, path in times[:top]:
            print(path, secs)


@cli.command()
@click.argument("vpath", type=str, required=True)
@click.option("--cache/--no-cache", default=False)
@click.pass_obj
def profile_page(pages, vpath, cache):
    """Tests the parsing time of a single wiki page."""

    indexer = pages.indexer()
    searcher = indexer.searcher()

    # Delete page from cache to make sure it's reparsed
    spath = pages.source_path(vpath)
    pages.cache.delete_path(spath)

    print("Parsing", spath)
    context = pages.wiki_context(spath, conditional=cache, save_to_cache=False,
                                 searcher=searcher, profiling=True)

    t = util.perf_counter()
    _ = pages.json(spath, wcontext=context)
    print("\nTotal time", util.perf_counter() - t)

    proc_times = context["proc_time"]
    for path, parse_secs in context["parse_time"]:
        print("%s %0.06f" % (path, parse_secs))
        # for procname, proc_secs in proc_times[path]:
        #     print("    %s %0.06f" % (procname, proc_secs))


def runhelp(*args):
    # The hhelp executable does some weird stuff I don't understand and runs
    # this function instead of starting the script from the command line in the
    # normal way. So here we have to invoke the main cli object as if it was run
    # from the command line, which fortunately click has a method for.
    cli.main(prog_name=args[0], args=args[1:])


if __name__ == '__main__':
    cli()
