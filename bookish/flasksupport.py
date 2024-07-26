import os
import threading

import werkzeug.serving

from bookish import config, flaskapp, paths, search
from bookish.wiki import styles, wikipages

from houdinihelp import hpages


class BackgroundIndexUnavailable(Exception):
    pass


indexlock = threading.Lock()


def setup(app):
    setup_logging(app)
    setup_store(app)
    setup_jinja(app)
    Scss(app)

    if not werkzeug.serving.is_running_from_reloader():
        BgIndex(app)


def setup_config(app, config_file=None, use_houdini_path=True):
    from houdinihelp import hconfig

    hconfig.read_houdini_config(app.config, config_file,
                                use_houdini_path=use_houdini_path)


def setup_logging(app):
    wikipages.logger_from_config(app.config, app.logger)


def setup_store(app):
    store = wikipages.store_from_config(app.config)
    app.store = store


def setup_jinja(app):
    store = app.store
    hpages.jinja_from_config(app.config, store, app.jinja_env)


class BgIndex(object):
    def __init__(self, app):
        self.enabled = app.config.get("ENABLE_BACKGROUND_INDEXING")
        self.autostart = app.config.get("AUTOSTART_BACKGROUND_INDEXING")
        self.interval = app.config.get("BACKGROUND_INDEXING_INTERVAL", 60.0)
        self.timer = None

        if self.enabled and self.autostart:
            self.app = app
            self.start_bg_indexing()

    def start_bg_indexing(self):
        locked = indexlock.acquire(False)
        if not locked:
            raise BackgroundIndexUnavailable
        if self.timer:
            raise Exception("Background indexing is already started")

        self.app.logger.info("Starting background indexing, interval %s s" %
                             self.interval)
        self.reschedule()

    def reschedule(self):
        self.timer = threading.Timer(self.interval, self.trigger, ())
        self.timer.daemon = True
        self.timer.start()

    def trigger(self):
        from bookish.search import LockError

        self.app.logger.info("Periodic reindex")

        pages = flaskapp.get_wikipages(self.app)
        indexer = pages.indexer()
        try:
            indexer.update(pages)
        except LockError:
            pass

        self.reschedule()


class Scss(object):
    def __init__(self, app):
        self.app = app
        if not app.config.get("AUTO_COMPILE_SCSS"):
            return

        try:
            import sass
        except ImportError:
            self.app.logger.info("libsass not available")
            return

        self.asset_dir = self.app.config.get("SCSS_ASSET_DIR")
        self.store = flaskapp.get_store(app)

        if not self.asset_dir:
            self.app.logger.warning("No SCSS_ASSET_DIR configured.")
            return

        # self.update_scss()
        if self.app.testing or self.app.debug:
            self.set_hooks()

    def set_hooks(self):
        # self.app.logger.info("Pyscss watching %r", self.asset_dir)
        self.app.before_request(self.update_scss)

    def find_scss(self, partials=False):
        for name in self.store.list_dir(self.asset_dir):
            if paths.extension(name) == ".scss":
                ispartial = name.startswith("_")
                if ispartial and not partials:
                    continue
                yield self.asset_dir + name, ispartial

    def output_path(self, path):
        assert path.endswith(".scss")
        return path.replace(".scss", ".css")

    def out_of_date(self, path):
        s = self.store
        mtime = s.last_modified(path)
        opath = self.output_path(path)
        if not s.exists(opath) or mtime > s.last_modified(opath):
            return True

    def partials_have_changed(self):
        for path, ispartial in self.find_scss(partials=True):
            if not ispartial:
                continue

            if self.out_of_date(path):
                return True

    def recompile_all(self):
        for path, _ in self.find_scss(partials=True):
            self.compile_scss(path)

    def update_scss(self):
        if self.partials_have_changed():
            return self.recompile_all()

        for path, _ in self.find_scss():
            if self.out_of_date(path):
                self.compile_scss(path)

    def import_hook(self, path):
        if not paths.is_abs(path):
            path = paths.join(self.asset_dir, path)
        if self.store.exists(path):
            return [(path, self.store.content(path))]

    def compile_scss(self, path):
        import os.path

        name = paths.barename(path)

        fp = self.store.file_path(path)
        outfp = os.path.join(os.path.dirname(fp), name + ".css")

        self.app.logger.info("SCSS compiling %s", fp)
        try:
            import sass
            css = sass.compile(filename=fp, precision=3,
                               importers=[(0, self.import_hook)])
        except:
            import sys
            e = sys.exc_info()[1]
            self.app.logger.error(str(e))
            raise
        else:
            with open(outfp, "w") as f:
                f.write(css)
