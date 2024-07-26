from __future__ import print_function

import calendar
import errno
import os.path
import re
import sys
import zipfile
from datetime import datetime
from hashlib import md5

from bookish import compat, paths, util
from bookish.wiki import langpaths
from bookish.compat import string_type

try:
    from zipfile import BadZipFile
except ImportError:
    from zipfile import BadZipfile as BadZipFile

try:
    import configparser
except ImportError:
    import ConfigParser as configparser


class PathManipulationError(Exception):
    pass


def file_etag(fpath):
    stat = os.stat(fpath)
    h = md5()
    h.update(str(stat.st_ino).encode("ascii"))
    h.update(str(stat.st_size).encode("ascii"))
    h.update(str(stat.st_mtime).encode("ascii"))
    return h.hexdigest()


# Utility functions

def expandpath(path, root_path=None):
    path = os.path.expanduser(os.path.expandvars(path))
    if root_path:
        path = os.path.join(root_path, path)
    else:
        path = os.path.abspath(path)
    return path


_gUTCOffset = None


def utc_offset():
    global _gUTCOffset

    if _gUTCOffset is None:
        local_now = datetime.now()
        utc_now = datetime.utcnow()
        _gUTCOffset = utc_now - local_now

    return _gUTCOffset


def store_from_spec(spec):
    if isinstance(spec, string_type):
        spec = {"type": "files", "dir": spec}

    if isinstance(spec, (list, tuple)):
        storelist = [store_from_spec(x) for x in spec]
        if len(storelist) == 1:
            return storelist[0]
        else:
            return OverlayStore(*storelist)

    elif isinstance(spec, Store):
        return spec

    elif not isinstance(spec, dict):
        raise ValueError("Don't know what to do with storage spec %r" % spec)

    spectype = spec["type"]
    if spectype == "files":
        return FileStore(expandpath(spec["dir"]))

    if spectype == "mount":
        source = store_from_spec(spec["source"])
        target = spec["target"]
        assert target.startswith("/")
        return MountStore(source, target)

    elif spectype == "wrapper":
        if "class" in spec:
            cls = spec["class"]
        else:
            cls = util.class_from_name(spec["classname"])
        child = store_from_spec(spec["child"])
        args = spec.get("args", {})
        return cls(child, **args)

    elif spectype == "object":
        if "class" in spec:
            cls = spec["class"]
        else:
            cls = util.class_from_name(spec["classname"])
        args = spec.get("args", {})
        return cls(**args)

    raise ValueError("Unknown store spec type %r" % spectype)


# Exceptions

class ResourceNotFoundError(Exception):
    pass


# Store objects

class Store(object):
    """
    Base class for page storage objects.
    """

    def __init__(self, config=None):
        self.config = config or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.close()

    def emit(self, tab, *strings):
        print("  "* tab, *strings)

    def dump(self, tab=0):
        self.emit(tab, "--")
        self.emit(tab, repr(self))

    def explain(self, path, tab=0):
        self.dump(tab)
        self.emit(tab, "path=", path, "exists=", self.exists(path))

    def tags(self):
        return ()

    def set_config(self, config):
        self.config = config

    def redirect(self, path):
        return None

    def settings(self, path, name="_settings.ini"):
        dirpath = paths.directory(path)
        parts = paths.split_path_parts(dirpath)
        settings = configparser.ConfigParser()
        for i in range(len(parts) + 1):
            spath = "/%s/%s" % ("/".join(parts[:i]), name)
            try:
                with self.open(spath, "r") as f:
                    settings.read_file(f, spath)
            except ResourceNotFoundError:
                continue
        return settings

    def store_for(self, path):
        if self.exists(path):
            return self

    def file_path(self, path):
        """
        Returns the filesystem equivalent of the given virtual path, if it has
        one, otherwise None.
        """

        return None

    def etag(self, path):
        return None

    def exists(self, path):
        """
        Returns True if the given path exists in this store.
        """

        raise NotImplementedError(self.__class__)

    def is_dir(self, path):
        """
        Returns True if the given path represents a directory in this store.
        """

        raise NotImplementedError(self.__class__)

    def extra_fields(self, path):
        return None

    def list_all(self, path="/", no_lang=False):
        if not path.endswith("/"):
            path += "/"

        if not self.exists(path):
            raise ResourceNotFoundError(path)

        for name in self.list_dir(path):
            if no_lang and path == "/" and name.startswith("+"):
                continue
            p = paths.join(path, name)
            if self.is_dir(p):
                for sp in self.list_all(p, no_lang=no_lang):
                    yield sp
            else:
                yield p

    def list_dir(self, path):
        """
        Lists the file names under the given path.
        """

        return ()

    def last_modified(self, path):
        """
        Returns a datetime object
        """

        return datetime.utcnow()

    def size(self, path):
        """
        Returns the size (in bytes) of the file at the given path.
        """

        return len(self.content(path, encoding=None))

    def open(self, path, mode="rb"):
        """
        Returns a file-like object for *reading* the given path.
        """

        raise NotImplementedError(self.__class__)

    def writable(self, path):
        """
        Returns True if the given path can be created/overwritten.
        """

        return False

    def make_dir(self, path, create_intermediate=False):
        """
        Creates a new directory at the given path.
        """

        raise Exception("%r can't create directories" % self)

    def write_file(self, path, bytestring):
        with self.open(path, "w+b") as f:
            f.write(bytestring)

    def move(self, path, newpath):
        """
        Moves the underlying file to the new path.
        """

        raise NotImplementedError(self.__class__)

    def delete(self, path):
        """
        Deletes the underlying file for the given path.
        """

        raise NotImplementedError(self.__class__)

    def content(self, path, encoding="utf8"):
        """
        Convenience method to return the string content of the file at the
        given path.

        :param encoding: the name of the encoding to use to decode the file's
            bytes. Default is ``"utf8"``. If you use ``encoding=None`` the
             method returns the raw bytestring.
        """

        with self.open(path) as f:
            string = f.read()

        if encoding:
            string = string.decode(encoding, "replace")

            # If the file starts with a BOM, throw it away
            if string.startswith(u"\ufeff"):
                string = string[1:]

        return string

    def close(self):
        pass


class FileStore(Store):
    """
    Represents a directory in the filesystem.
    """

    def __init__(self, dirpath, config=None):
        super(FileStore, self).__init__(config=config)
        self.dirpath = expandpath(dirpath)

    def __repr__(self):
        return "<%s %r>" % (type(self).__name__, self.dirpath)

    def explain(self, path, tab=0):
        self.dump(tab)
        self.emit(tab, "path=", path)
        self.emit(tab, "file=", self.file_path(path))
        self.emit(tab, "exists=", self.exists(path))

    def file_path(self, path):
        path = paths.normalize_abs(path)
        return os.path.join(self.dirpath, path[1:])

    def etag(self, path):
        fpath = self.file_path(path)
        if os.path.exists(fpath):
            return file_etag(fpath)

    def exists(self, path):
        return path and os.path.exists(self.file_path(path))

    def is_dir(self, path):
        try:
            filepath = self.file_path(path)
            return os.path.isdir(filepath)
        except OSError:
            e = sys.exc_info()[1]
            if e.errno == errno.ENOENT:
                raise ResourceNotFoundError(path)

    def list_dir(self, path):
        file_path = self.file_path(path)
        try:
            fnames = os.listdir(file_path)
        except OSError:
            e = sys.exc_info()[1]
            if e.errno == errno.ENOENT:
                raise ResourceNotFoundError("%s (%s)" % (path, file_path))
            else:
                raise

        return [fname for fname in fnames if not fname.startswith(".")]

    def last_modified(self, path):
        try:
            mtime = os.path.getmtime(self.file_path(path))
        except OSError:
            e = sys.exc_info()[1]
            if e.errno == errno.ENOENT:
                raise ResourceNotFoundError(path)
            else:
                raise

        return datetime.utcfromtimestamp(mtime)

    def size(self, path):
        try:
            return os.path.getsize(self.file_path(path))
        except OSError:
            e = sys.exc_info()[1]
            if e.errno == errno.ENOENT:
                raise ResourceNotFoundError(path)

    def open(self, path, mode="rb"):
        try:
            return open(self.file_path(path), mode)
        except IOError:
            e = sys.exc_info()[1]
            if e.errno == errno.ENOENT:
                raise ResourceNotFoundError(path)
            else:
                raise

    def writable(self, path):
        filepath = self.file_path(path)
        dirpath = os.path.dirname(filepath)
        try:
            return os.access(dirpath, os.W_OK)
        except OSError:
            e = sys.exc_info()[1]
            if e.errno == errno.ENOENT:
                raise ResourceNotFoundError(path)
            else:
                raise

    def make_dir(self, path, create_intermediate=False):
        if create_intermediate:
            os.makedirs(self.file_path(path))
        else:
            os.mkdir(self.file_path(path))

    def move(self, path, newpath):
        filepath = self.file_path(path)
        newfilepath = self.file_path(newpath)
        try:
            os.rename(filepath, newfilepath)
        except OSError:
            e = sys.exc_info()[1]
            if e.errno == errno.ENOENT:
                raise ResourceNotFoundError(path)
            else:
                raise

    def delete(self, path):
        filepath = self.file_path(path)

        if os.path.isdir(filepath):
            os.rmdir(filepath)
        else:
            try:
                os.remove(filepath)
            except OSError:
                e = sys.exc_info()[1]
                if e.errno == errno.ENOENT:
                    raise ResourceNotFoundError(path)
                else:
                    raise


class ZipTree(Store):
    """
    Looks for a zip file corresponding to the first part of a path, and if it
    finds one, looks inside that zip file for the rest of the path. This
    essentially makes zip files at the root level look like directories.
    """

    _top_exp = re.compile("/([^/]+)")

    def __init__(self, dirpath, config=None):
        super(ZipTree, self).__init__(config=config)
        self.dirpath = expandpath(dirpath)
        self.stores = {}

    def __repr__(self):
        return "<%s %r>" % (type(self).__name__, self.dirpath)

    @staticmethod
    def _splittable(path):
        return path.find("/", 1) > -1

    @staticmethod
    def _split_path(path):
        i = path.find("/", 1)
        assert i >= 0
        return path[1:i], path[i:]

    def explain(self, path, tab=0):
        self.dump(tab)
        self.emit(tab, "path=", path)
        self.exists(path, _explain=True, _tab=tab)

    def _zip_filepath(self, first):
        zippath = os.path.join(self.dirpath, first + ".zip")
        if os.path.exists(zippath):
            return zippath

    def _zip_store(self, first):
        if first in self.stores:
            return self.stores[first]

        zippath = self._zip_filepath(first)
        if zippath:
            store = self.stores[first] = ZipStore(zippath)
            return store

    def _perform(self, path, fn):
        if self._splittable(path):
            first, rest = self._split_path(path)
            s = self._zip_store(first)
            if s:
                return fn(s, rest)
        raise ResourceNotFoundError(path)

    def etag(self, path):
        if self._splittable(path):
            first, _ = self._split_path(path)
            zpath = self._zip_filepath(first)
            if zpath:
                return file_etag(zpath)
        raise ResourceNotFoundError(path)

    def exists(self, path, _explain=False, _tab=0):
        if path == "/":
            if _explain:
                self.emit(_tab, "path / always exists")
            return True

        if self._splittable(path):
            first, rest = self._split_path(path)
            s = self._zip_store(first)
            if _explain:
                self.emit(_tab, "first=", first, "rest=", rest)
                self.emit("store=", s)
            if s:
                if rest == "/":
                    if _explain:
                        self.emit(_tab, "path / always exists inside a zip")
                    return True
                if _explain:
                    s.explain(rest)
                return s.exists(rest)
        else:
            m = self._top_exp.match(path)
            if _explain:
                self.emit(_tab, "zip name match=", m)
            if m:
                if _explain:
                    self.emit(_tab, "zip store=", self._zip_store(m.group(1)))
                return bool(self._zip_store(m.group(1)))
            return False

    def is_dir(self, path):
        if self._splittable(path):
            return self._perform(path, lambda s, rest: s.is_dir(rest))
        else:
            m = self._top_exp.match(path)
            if m:
                s = self._zip_store(m.group(1))
                if s:
                    return True

            raise ResourceNotFoundError(path)

    def list_all(self, path="/", no_lang=False):
        for filename in os.listdir(self.dirpath):
            if not filename.endswith(".zip"):
                continue
            if no_lang and path == "/" and filename.startswith("+"):
                continue

            name = filename[:-4]
            base = "/" + name
            zipstore = self._zip_store(name)
            if zipstore:
                for p in zipstore.list_all():
                    pp = base + p
                    if pp.startswith(path):
                        yield pp

    def list_dir(self, path):
        return self._perform(path, lambda s, rest: s.list_dir(rest))

    def last_modified(self, path):
        first, rest = self._split_path(path)
        zipstore = self._zip_store(first)
        return zipstore.last_modified(rest)

    def size(self, path):
        return self._perform(path, lambda s, rest: s.size(rest))

    def content(self, path, encoding="utf8"):
        return self._perform(
            path, lambda s, rest: s.content(rest, encoding=encoding)
        )

    def open(self, path, mode="rb"):
        return self._perform(path, lambda s, rest: s.open(rest, mode=mode))

    def close(self):
        for s in self.stores.values():
            s.close()

    def move(self, path, newpath):
        raise Exception("Cannot move %r, ZipTree is read-only" % path)

    def delete(self, path):
        raise Exception("Cannot delete %r, ZipTree is read-only" % path)


class ZipStore(Store):
    """
    Represents the files inside a zip archive.
    """

    def __init__(self, zipfilepath, config=None):
        super(ZipStore, self).__init__(config=config)
        self.zipfilepath = expandpath(zipfilepath)
        self._zipfile = None
        self.valid = True
        self.modtime = None
        self._exists_cache = {}
        self._is_dir_cache = {}

    @property
    def zipfile(self):
        if self._zipfile is None:
            try:
                self._zipfile = zipfile.ZipFile(self.zipfilepath, "r")
            except IOError:
                self.valid = False
            except BadZipFile:
                raise Exception("File %s is not a valid Zip file" %
                                self.zipfilepath)
        return self._zipfile

    @staticmethod
    def zipname(path):
        return paths.normalize_abs(path)[1:]

    def explain(self, path, tab=0):
        self.dump(tab)
        self.emit(tab, "path=", path)
        zname = self.zipname(path)
        zdirname = zname if zname.endswith("/") else zname + "/"
        self.emit(tab, "zip name=", zname)
        self.emit(tab, "zip dir name=", zdirname)
        self.emit(tab, "exists=", self.exists(path))

    def zipinfo(self, path):
        return self.zipfile.getinfo(self.zipname(path))

    def etag(self, path):
        return file_etag(self.zipfilepath)

    def exists(self, path):
        if path in self._exists_cache:
            return self._exists_cache[path]
        exists = self._do_exists(path)
        self._exists_cache[path] = exists
        return exists

    def _do_exists(self, path):
        zipfile = self.zipfile
        if not self.valid:
            return False

        zname = self.zipname(path)
        zdirname = zname if zname.endswith("/") else zname + "/"
        for zpath in zipfile.namelist():
            if zpath == zname or zpath.startswith(zdirname):
                return True
        return False

    def is_dir(self, path):
        if path in self._is_dir_cache:
            return self._is_dir_cache[path]

        res = self._do_is_dir(path)
        self._is_dir_cache[path] = res
        return res

    def _do_is_dir(self, path):
        if not self.valid:
            return False

        for _ in self.list_dir(path):
            return True
        return False

    def list_all(self, path="/", no_lang=False):
        if not self.valid:
            return

        assert path.startswith("/")
        if not path.endswith("/"):
            path += "/"

        for n in self.zipfile.namelist():
            zp = "/" + n
            if not zp.startswith(path):
                continue
            yield zp

    def list_dir(self, path):
        if not self.valid:
            raise ResourceNotFoundError(path)

        if not path.endswith("/"):
            path += "/"
        zippath = self.zipname(path)
        names = set()
        for name in self.zipfile.namelist():
            if name.startswith(zippath):
                basename = name[len(zippath):].split("/")[0]
                names.add(basename)
        return sorted(names)

    def last_modified(self, path):
        if not self.valid:
            raise ResourceNotFoundError(path)

        t = self.zipinfo(path).date_time
        t = calendar.timegm(t)

        # The timestamp is supposed to be UTC, but Python's ZipInfo has a bug,
        # so we need to add the UTC offset again
        return datetime.utcfromtimestamp(t) + utc_offset()

        # if not self.modtime:
        #     mtime = os.path.getmtime(self.zipfilepath)
        #     self.modtime = datetime.utcfromtimestamp(mtime)
        # return self.modtime

    def size(self, path):
        if not self.valid:
            raise ResourceNotFoundError(path)

        return self.zipinfo(path).file_size

    def content(self, path, encoding="utf8"):
        if not self.valid:
            raise ResourceNotFoundError(path)

        try:
            string = self.zipfile.read(self.zipname(path))
        except KeyError:
            raise ResourceNotFoundError(path)

        if encoding:
            string = string.decode("utf8")
        return string

    def open(self, path, mode="r"):
        if not self.valid:
            raise ResourceNotFoundError(path)

        return self.zipfile.open(self.zipname(path), "r")

    def close(self):
        if self.valid:
            self.zipfile.close()

    def move(self, path, newpath):
        raise Exception("Cannot move %r, ZipStore is read-only" % path)

    def delete(self, path):
        raise Exception("Cannot delete %r, ZipStore is read-only" % path)


class WrappingStore(Store):
    """
    Base class for PageStore implementations that wrap "child" stores.
    """

    def __init__(self, child):
        self.child = child

    def set_config(self, config):
        self.child.set_config(config)

    def dump(self, tab=0):
        super(WrappingStore, self).dump(tab)
        self.child.dump(tab + 1)

    def explain(self, path, tab=0):
        self.dump(tab)
        self.emit(tab, "path=", path)
        xpath = self._xlate_down(path)
        self.emit(tab, "translated path=", xpath)
        self.child.explain(xpath, tab + 1)

    def extra_fields(self, path):
        return self.child.extra_fields(self._xlate_down(path))

    @property
    def config(self):
        return self.child.config

    def _xlate_up(self, path):
        return path

    def _xlate_down(self, path):
        return path

    def redirect(self, path):
        try:
            newpath = self.child.redirect(self._xlate_down(path))
            if newpath is not None:
                return self._xlate_up(newpath)
        except PathManipulationError:
            return None

    def file_path(self, path):
        return self.child.file_path(self._xlate_down(path))

    def etag(self, path):
        return self.child.etag(self._xlate_down(path))

    def exists(self, path):
        return self.child.exists(self._xlate_down(path))

    def is_dir(self, path):
        return self.child.is_dir(self._xlate_down(path))

    def list_all(self, path="/", no_lang=False):
        for path in self.child.list_all(path=self._xlate_down(path)):
            up = self._xlate_up(path)
            if no_lang and up.startwisth("/+"):
                continue
            yield up

    def list_dir(self, path):
        return self.child.list_dir(self._xlate_down(path))

    def last_modified(self, path):
        return self.child.last_modified(self._xlate_down(path))

    def size(self, path):
        return self.child.size(self._xlate_down(path))

    def content(self, path, encoding="utf8"):
        return self.child.content(path, encoding=encoding)

    def open(self, path, mode="rb"):
        return self.child.open(self._xlate_down(path), mode)

    def make_dir(self, path, create_intermediate=False):
        return self.child.make_dir(self._xlate_down(path), create_intermediate)

    def move(self, path, newpath):
        return self.child.move(self._xlate_down(path),
                               self._xlate_down(newpath))

    def delete(self, path):
        return self.child.delete(self._xlate_down(path))

    def writable(self, path):
        return self.child.writable(self._xlate_down(path))

    def close(self):
        self.child.close()


class CommonLang(WrappingStore):
    """
    Projects root directories into all languages.
    """

    # TODO: fix this
    def _xlate(self, path):
        if not self.child.exists(path) and langpaths.has_lang(path):
            return langpaths.delang(path)

        return path


class SubStore(WrappingStore):
    """
    "Extracts" a "sub-directory" of a child store and presents it as a top-level
    store.
    """

    def __init__(self, child, prefix):
        self.child = child
        self.prefix = prefix

    def _xlate_down(self, path):
        return self.prefix + path

    def _xlate_up(self, path):
        if path.startswith(self.prefix):
            return path[len(self.prefix):]
        else:
            return path


class MountStore(WrappingStore):
    """
    Mounts a child store at a "sub-directory", for use in an OverlayStore.
    """

    def __init__(self, child, prefix):
        self.child = child
        self.prefix = prefix

    def __repr__(self):
        return "<%s %r at %r>" % (type(self).__name__, self.child, self.prefix)

    def explain(self, path, tab=0):
        self.dump(tab)
        check = self._check(path)
        self.emit(tab, "contained=", check)
        if check:
            xpath = self._xlate_down(path)
            self.emit(tab, "translated path=", xpath)
            self.child.explain(xpath, tab + 1)

    def _check(self, path):
        prefix = self.prefix
        prelen = len(prefix)
        return (
            path.startswith(prefix)
            and len(path) > prelen
            and path[prelen] == "/"
        )

    def _xlate_down(self, path):
        if not self._check(path):
            raise PathManipulationError("%r can't translate path %r" %
                                        (self, path))
        return path[len(self.prefix):]

    def _xlate_up(self, path):
        return self.prefix + path

    def extra_fields(self, path):
        if self._check(path):
            return self.child.extra_fields(self._xlate_down(path))

    def content(self, path, encoding="utf8"):
        if not self._check(path):
            raise ResourceNotFoundError(path)
        return self.child.content(self._xlate_down(path), encoding)

    def is_dir(self, path):
        if not path.startswith(self.prefix):
            return False
        return self.child.is_dir(self._xlate_down(path))

    def list_all(self, path="/", no_lang=False):
        if not path.startswith(self.prefix):
            return

        path = self._xlate_down(path)
        if not path.endswith("/"):
            path += "/"
        for p in self.child.list_all(path):
            pp = self.prefix + p
            yield pp

    def list_dir(self, path):
        if self._check(path):
            return WrappingStore.list_dir(self, path)
        else:
            return []

    def exists(self, path):
        return self._check(path) and self.child.exists(self._xlate_down(path))


class HideStore(WrappingStore):
    """
    Calls a function to check whether a given file exists. If the function
    returns True, the file is retrieved from the wrapped store.
    """

    def __repr__(self):
        return "<%s %r>" % (type(self).__name__, self.child)

    def _check(self, path):
        return True

    def explain(self, path, tab=0):
        self.dump()
        self.emit(tab, "path=", path)
        check = self._check(path)
        self.emit(tab, "check=", check)
        if check:
            xpath = self._xlate_down(path)
            self.emit(tab, "translated path=", xpath)
            self.child.explain(xpath, tab + 1)

    def content(self, path, encoding="utf8"):
        if not self._check(path):
            raise ResourceNotFoundError(path)
        return self.child.content(self._xlate_down(path), encoding)

    def is_dir(self, path):
        if not self._check(path):
            return False
        return self.child.is_dir(self._xlate_down(path))

    def list_all(self, path="/", no_lang=False):
        if not self._check(path):
            return

        for p in self.child.list_all(self._xlate_down(path)):
            p = self._xlate_up(p)
            if no_lang and p.startswith("/+"):
                continue
            if not self._check(p):
                continue
            yield p

    def list_dir(self, path):
        for name in self.child.list_dir(self._xlate_down(path)):
            path = paths.join(path, name)
            if not self._check(path):
                continue
            yield name

    def exists(self, path):
        if not self._check(path):
            return False
        return self.child.exists(self._xlate_down(path))


class OverlayStore(Store):
    """
    Overlays the contents of a number of sub-stores. When the methods are called
    with a path, this store tries its sub-stores in order, and fulfills the
    request using the first sub-store found that contains the path.
    """

    def __init__(self, *stores):
        self.stores = []
        for store in stores:
            if isinstance(store, OverlayStore):
                self.stores.extend(store.stores)
            else:
                self.stores.append(store)

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__,
                           ", ".join(repr(s) for s in self.stores))

    def dump(self, tab=0):
        super(OverlayStore, self).dump(tab)
        for store in self.stores:
            store.dump(tab + 1)

    def explain(self, path, tab=0):
        self.dump(tab)
        self.emit(tab, "path=", path)
        self.emit(tab, "exists=", self.exists(path))
        for store in self.stores:
            store.explain(path, tab + 1)

    def set_config(self, config):
        for store in self.stores:
            store.set_config(config)

    def redirect(self, path):
        for store in self.stores:
            newpath = store.redirect(path)
            if newpath is not None:
                return newpath

    def extra_fields(self, path):
        for store in self.stores:
            ex = store.extra_fields(path)
            if ex is not None:
                return ex

    def store_for(self, path):
        for store in self.stores:
            if store.exists(path):
                return store

    def append(self, store):
        self.stores.append(store)

    def extend(self, stores):
        self.stores.extend(stores)

    def file_path(self, path):
        s = self.store_for(path)
        if s:
            return s.file_path(path)

    def etag(self, path):
        for store in self.stores:
            if store.exists(path):
                return store.etag(path)

    def exists(self, path):
        return any(s.exists(path) for s in self.stores)

    def is_dir(self, path):
        for s in self.stores:
            if s.exists(path):
                return s.is_dir(path)
        raise ResourceNotFoundError(path)

    def list_all(self, path="/", no_lang=False):
        seen = set()
        for store in self.stores:
            if store.exists(path):
                seen.update(store.list_all(path, no_lang=False))
        return sorted(seen)

    def list_dir(self, path):
        seen = set()
        for store in self.stores:
            if store.exists(path):
                seen.update(store.list_dir(path))
        return sorted(seen)

    def last_modified(self, path):
        s = self.store_for(path)
        if not s:
            raise ResourceNotFoundError(
                f"Couldn't find {path} in any of {self.stores!r}"
            )
        return s.last_modified(path)

    def size(self, path):
        s = self.store_for(path)
        if not s:
            raise ResourceNotFoundError(
                f"Couldn't find {path} in any of {self.stores!r}"
            )
        return s.size(path)

    def open(self, path, mode="rb"):
        s = self.store_for(path)
        if not s:
            raise ResourceNotFoundError(
                f"Couldn't find {path} in any of {self.stores!r}"
            )
        return s.open(path, mode)

    def content(self, path, encoding="utf8"):
        s = self.store_for(path)
        if not s:
            raise ResourceNotFoundError(
                f"Couldn't find {path} in any of {self.stores!r}"
            )
        return s.content(path, encoding=encoding)

    def writable(self, path):
        s = self.store_for(path)
        if not s:
            raise ResourceNotFoundError(
                f"Couldn't find {path} in any of {self.stores!r}"
            )
        return s.writable(path)

    def make_dir(self, path, create_intermediate=False):
        raise Exception("Can't create a directory in an overlay store")

    def write_file(self, path, bytestring):
        raise Exception("Can't write a file to an overlay store")

    def delete(self, path):
        s = self.store_for(path)
        if not s:
            raise ResourceNotFoundError(
                f"Couldn't find {path} in any of {self.stores!r}"
            )
        return s.delete(path)

    def move(self, path, newpath):
        s = self.store_for(path)
        if not s:
            raise ResourceNotFoundError(
                f"Couldn't find {path} in any of {self.stores!r}"
            )
        return s.move(path, newpath)

    def close(self):
        for store in self.stores:
            store.close()


class SelectedLang(WrappingStore):
    """
    Overlays selected language tree over the root.
    """

    def __init__(self, child):
        self._child = child
        self._lang = "en"
        self._stores = (self._child,)

    @property
    def stores(self):
        lang = os.environ.get("HOUDINI_HELP_LANG", "en")
        if lang != self._lang:
            self._lang = lang
            if lang == "en":
                self._stores = (self._child,)
            else:
                self._stores = (SubStore(self._child, "/" + lang), self._child)
        return self._stores


class StringStore(Store):
    """
    Base class for stores that more naturally return generate strings than
    file-like objects
    """

    def is_dir(self, path):
        raise NotImplementedError(self.__class__)

    def explain(self, path, tab=0):
        self.dump(tab)
        self.emit(tab, "StringStore does not implement exists")

    def exists(self, path):
        raise NotImplementedError(self.__class__)

    def move(self, path, newpath):
        raise NotImplementedError(self.__class__)

    def delete(self, path):
        raise NotImplementedError(self.__class__)

    def content(self, path, encoding="utf8"):
        raise NotImplementedError(self.__class__)

    def open(self, path, mode="rb"):
        assert mode == "rb"
        try:
            # TODO: This should be bytes, but Houdini will randomly return
            # unicode based on the contents of the data
            content = self.content(path, encoding=None)
        except KeyError:
            raise ResourceNotFoundError(path)
        # assert isinstance(content, compat.bytes_type)
        return compat.BytesIO(content)


class DictionaryStore(Store):
    """
    Presents a dictionary mapping path strings to bytes objects as a page store.

    Supports the ``list_all(path)`` method but does not support directories
    (``list_dir`` always returns ``[]`` and ``is_dir`` always returns False).

    Does not support last modified times (``last_modified`` always returns 0).
    """

    def __init__(self, dictionary, writable=False, config=None):
        super(DictionaryStore, self).__init__(config=config)
        self.dict = dictionary
        self._writable = writable
        self._reset_time()

    def _reset_time(self):
        self._time = datetime.utcnow()

    def _check(self, path):
        if not path.startswith("/"):
            raise ValueError("Paths must be absolute")
        return path

    def etag(self, path):
        if self.exists(path):
            return str(self._time)

    def exists(self, path):
        return self._check(path) in self.dict

    def delete(self, path):
        del self.dict[self._check(path)]

    def move(self, path, newpath):
        self.dict[self._check(newpath)] = self.dict.pop(self._check(path))

    def is_dir(self, path):
        return False

    def list_all(self, path="/", no_lang=False):
        if not path.endswith("/"):
            path += "/"
        for p in sorted(self.dict):
            if no_lang and p.startswith("/+"):
                continue
            if p.startswith(path):
                yield p
            elif p > path:
                break

    def list_dir(self, path):
        return []

    def last_modified(self, path):
        return self._time

    def size(self, path):
        path = self._check(path)
        try:
            bytestring = self.dict[path]
        except KeyError:
            raise ResourceNotFoundError(path)
        return len(bytestring)

    def open(self, path, mode="rb"):
        assert mode == "rb"
        path = self._check(path)
        try:
            bytestring = self.dict[path]
        except KeyError:
            raise ResourceNotFoundError(path)
        return compat.BytesIO(bytestring)

    def writable(self, path):
        return self._writable

    def write_file(self, path, bytestring):
        assert self._writable
        self.dict[path] = bytestring
        self._reset_time()

    def make_dir(self, path, create_intermediate=False):
        raise Exception("DictionaryStore doesn't support directories")




