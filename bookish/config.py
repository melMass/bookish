import os.path
import sys

from bookish import search
from bookish.text import textify


this_dir = os.path.abspath(os.path.dirname(__file__))


def expandpath(path):
    path = path.replace("${PYTHON_VERSION}", "%s.%s" %
                        (sys.version_info.major, sys.version_info.minor))
    return os.path.expanduser(os.path.expandvars(path))


def read_config(cfg=None, config_file=None, root_path=".", config_obj=None):
    from bookish.wiki import config
    from bookish.stores import expandpath

    cfg = cfg or config.Config(root_path)
    cfg.from_object(config_obj or DefaultConfig)

    if config_file:
        config_file = expandpath(config_file, root_path=root_path)
        cfg.from_pyfile(config_file)

    cfg.from_envvar("BOOKISH_CONFIG", silent=True)

    return cfg


class DefaultConfig(object):
    # Flask configuration

    SECRET_KEY = 'dummy'
    DEBUG = False

    # Bookish configuration

    # Some variables that can be used in templates
    ICON_32 = "/images/logos/logo_32.png"
    ICON_144 = "/images/logos/logo_144.png"
    PYGMENTS_CSS = "/static/css/pygments/brightcolor.css"

    # Basic filesystem of support directories.
    # This is a Storage specification (to be interpreted by
    # stores.store_from_spec()).
    SUPPORT_DOCUMENTS = [
        {
            "type": "mount",
            "source": os.path.join(this_dir, "templates"),
            "target": "/templates",
        }, {
            "type": "mount",
            "source": os.path.join(this_dir, "grammars"),
            "target": "/grammars",
        }, {
            "type": "mount",
            "source": os.path.join(this_dir, "static"),
            "target": "/static",
            "static": True,
        }
    ]

    # Storage spec for actual user documents (to be interpreted by
    # stores.store_from_spec())
    DOCUMENTS = []

    # Extra documents to be added in user configuration (this is easier than
    # extending DOCUMENTS)
    EXTRA_DOCUMENTS = []

    # Directory of SCSS files to compile into CSS
    SCSS_ASSET_DIR = "/static/scss/"

    # True if documents should be editable in the browser
    EDITABLE = False
    # Storage spec for where edited files should be stored
    EDIT_STORE = None

    # The template to use when rendering Wiki markup to HTML
    WIKI_STYLE = "/templates/wiki.jinja2"
    # Virtual path to the template to use for wiki pages
    TEMPLATE = "/templates/page.jinja2"
    # Virtual path to the template to use for search results
    SEARCH_TEMPLATE = "/templates/results.jinja2"

    # A bookish.wikipages.WikiPages subclass to use to generate wiki pages
    PAGES_CLASS = "bookish.wiki.wikipages.WikiPages"
    # A system file path to a directory in which to store cache files
    CACHE_DIR = "./cache"

    # A system file path to a directory in which to store the full-text index
    INDEX_DIR = "./index"
    # A bookish.search.Searchables instance to use to translate wiki pages into
    # searchable information
    SEARCHABLES = "bookish.search.Searchables"
    # True if the server should run an indexing thread in the background
    ENABLE_BACKGROUND_INDEXING = False
    # Number of seconds between background indexing runs
    BACKGROUND_INDEXING_INTERVAL = 60

    # Stash an automatic checkpoint while editing
    AUTOSAVE = True
    # Max number of seconds between stashing automatic checkpoint
    AUTOSAVE_SECONDS = 10
    # Max number of checkpoints to save
    CHECKPOINT_MAX = 10

    # A bookish.textify.Textifier subclass to use for translating wiki pages
    # into plain text
    TEXTIFY_CLASS = textify.TextifierBase

    # The base name for directory index pages
    INDEX_PAGE_NAME = "index"
    # The file extension for wiki pages
    WIKI_EXT = ".txt"

    # The default language for wiki pages
    DEFAULT_LANGUAGE = "en"
    # The default locale for wiki pages
    DEFAULT_LOCALE = "en_US"

    # A space-separated string setting the order of categories in search results
    CATEGORIES = ""

    # A list of {"shortcut": "x", "query": "type:x", "desc": "Description"}
    # dictionaries, specifying search shortcuts
    SEARCH_SHORTCUTS = []



