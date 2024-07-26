import re

from bookish import paths


PREFIX = "/+"
LANG_REGEX = re.compile(
    "^%s([A-Za-z0-9]{2,}([-][A-Za-z0-9]{2,})*($|(?=/)))" % re.escape(PREFIX),
    re.IGNORECASE
)


def has_lang(path):
    return path.startswith(PREFIX)


def _lang_match(path):
    # Checks the path and returns the match object from LANG_REGEX.

    if not paths.is_abs(path):
        raise ValueError("Paths must be absolute")

    match = LANG_REGEX.match(path)
    if not match:
        raise ValueError("Can't delang: %r has no language prefix" % path)
    return match


def split_lang_and_path(path):
    """
    Takes a language-aware path and returns two strings: the language name and
    the language-naive path. For example, `split_lang_and_path("/+en/foo")`
    returns a tuple of `"en"` and `"/foo"`.
    """

    match = _lang_match(path)
    dpath = path[match.end():]
    if not dpath:
        raise ValueError("Delanged path %r is empty" % path)
    return match.group(1), dpath


def lang_name(path):
    name, _ = split_lang_and_path(path)
    return name


def is_lang_root(path):
    """
    Returns True if the given path refers to a language root (and NOT anything
    under the language root). For example `"/+en"` or `"/+jp/"`.
    """

    if not paths.is_abs(path):
        raise ValueError("Paths must be absolute")
    langpart = _lang_match(path).group(0)
    return path == langpart or path == langpart + "/"


def delang(path):
    """
    Takes a language-aware path (e.g. `"/+en/foo/bar"`) and returns the
    equivalent language-naive path (e.g. `"/foo/bar"`).
    """

    _, dpath = split_lang_and_path(path)
    return dpath


def safe_delang(path):
    if not has_lang(path):
        return path
    return delang(path)


def enlang(name, path):
    """
    Takes a language name and a language-naive path (for example, `"en"` and
    `"/foo/bar"`) and returns the equivalent language-aware path (e.g.
    `"/+en/foo/bar"`).
    """

    if not paths.is_abs(path):
        raise ValueError("Paths must be absolute")
    if has_lang(path):
        raise ValueError("Can't enlang: %r already has a prefix" % path)

    return PREFIX + name + path





