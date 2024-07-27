import os
import sys

from bookish.config import DefaultConfig
from bookish.stores import expandpath

from houdinihelp.hcoloring import VexLexer, OpenCLLexer, HScriptLexer
from houdinihelp.usd import UsdLexer


ver_major = ver_minor = ver_build = ""
houdini_version = os.environ.get("HOUDINI_VERSION")
if houdini_version:
    ver_major, ver_minor, ver_build = houdini_version.split(".", 2)


class HoudniBaseConfig(DefaultConfig):
    USE_HOU = True
    DEBUG = False
    LOGLEVEL = "WARNING"
    PYGMENTS_CSS = "/static/css/pygments/autumn.css"

    HOUDINI_VERSION_MAJOR = ver_major
    HOUDINI_VERSION_MINOR = ver_minor
    HOUDINI_VERSION_BUILD = ver_build

    # Extra documents to be added in user configuration (this is easier than
    # extending DOCUMENTS)
    EXTRA_DOCUMENTS = []

    # A system file path to a directory in which to store cache files
    CACHE_DIR = "$HOUDINI_USER_PREF_DIR/config/Help/cache"

    # A system file path to a directory in which to store the full-text index
    INDEX_DIR = "$HFS/houdini/config/Help/index"

    INDEX_USAGES = True

    INDEX_IGNORE_FILE = None

    # True if the server should run an indexing thread in the background
    ENABLE_BACKGROUND_INDEXING = False
    # Number of seconds between background indexing runs
    BACKGROUND_INDEXING_INTERVAL = 60

    # Use a custom WikiPages class to get Houdini-specific page processors
    PAGES_CLASS = "houdinihelp.hpages.HoudiniPages"
    # Use a custom Searchables class to get Houdini-specific indexed fields
    SEARCHABLES = "houdinihelp.hsearch.HoudiniSearchables"

    TEXTIFY_CLASS = "houdinihelp.htextify.HoudiniTextifier"

    # Virtual path to wiki rendering style for Houdini-specific markup
    WIKI_STYLE = "/templates/hwiki.jinja2"
    # Virtual path to the template to use for wiki pages
    TEMPLATE = "/templates/hpage.jinja2"
    # Virtual path to the template to use for search results
    SEARCH_TEMPLATE = "/templates/hresults.jinja2"

    LEXERS = {
        "vex": VexLexer,
        "ocl": OpenCLLexer,
        "hscript": HScriptLexer,
        "usd": UsdLexer,
    }

    # Houdini-specific search shortcuts
    SHORTCUTS = [
        {"shortcut": "n",
         "query": "type:node",
         "desc": "All nodes",
         },
        {"shortcut": "s",
         "query": "category:node/sop",
         "desc": "Geometry nodes (SOPs)",
         },
        {"shortcut": "d",
         "query": "category:node/dop",
         "desc": "Dynamics nodes (DOPs)",
         },
        {"shortcut": "o",
         "query": "category:node/obj",
         "desc": "Object nodes",
         },
        {"shortcut": "v",
         "query": "(category:vex OR category:node/vop)",
         "desc": "VEX and VOPs",
         },
        {"shortcut": "vo",
         "query": "category:node/vop",
         "desc": "VOPs",
         },
        {"shortcut": "vx",
         "query": "type:vex",
         "desc": "VEX functions",
         },
        {"shortcut": "r",
         "query": "(category:node/out OR type:property)",
         "desc": "Render nodes and properties",
         },
        {"shortcut": "t",
         "query": "category:node/top",
         "desc": "TOP nodes",
         },
        {"shortcut": "p",
         "query": "category:hom*",
         "desc": "Python scripting (HOM)",
         },
        {"shortcut": "e",
         "query": "type:expression",
         "desc": "Expression functions",
         },
    ]

    EXTRA_SHORTCUTS = []

    # Houdini specific category ordering in search results
    CATEGORIES = """
        _ tool
        node/sop node/dop node/obj node/vop node/out node/cop2 node/chop node/vex
        node/top attribute vex example homclass hommethod homfunction hommodule
        expression hscript property env_variable
        """

    AUTO_COMPILE_SCSS = False
    

_HFS_MODULE_PATH = \
    "$HFS/houdini/python{}.{}libs".format(
        sys.version_info.major, sys.version_info.minor)


class HoudiniHfsConfig(HoudniBaseConfig):
    SUPPORT_DOCUMENTS = [
        {
            "type": "mount",
            "source": "{}/bookish/templates".format(_HFS_MODULE_PATH),
            "target": "/templates",
        }, {
            "type": "mount",
            "source": "{}/bookish/grammars".format(_HFS_MODULE_PATH),
            "target": "/grammars",
        },
        {
            "type": "mount",
            "source": "{}/houdinihelp/templates".format(_HFS_MODULE_PATH),
            "target": "/templates",
        },
        {
            "type": "mount",
            "source": "$HFS/houdini/toolbar",
            "target": "/toolbar",
        },
        {
            "type": "mount",
            "source": "$HFS/houdini/config",
            "target": "/icon_config"
        }
    ]

    # Storage spec for actual user documents (to be interpreted by
    # stores.store_from_spec())
    DOCUMENTS = [
        {
            # Get documents from @/help (this includes $HFS/houdini/help,
            # but we can't guarantee getting the path will work during the
            # build)
            "type": "object",
            "classname": "houdinihelp.hstores.HoudiniPathStore",
        },
        "$HFS/houdini/help",
        {
            # Adds ability to read docs out of .zip files in
            # $HFS/houdini/help
            "type": "object",
            "classname": "bookish.stores.ZipTree",
            "args": {
                "dirpath": expandpath("$HFS/houdini/help"),
            }
        }, {
            "type": "wrapper",
            "classname": "houdinihelp.hstores.ManagerRedirectStore",
            "child": {
                "type": "mount",
                "source": {
                    "type": "object",
                    "classname": "bookish.stores.ZipStore",
                    "args": {
                        "zipfilepath": "$HFS/houdini/help/nodes.zip"
                    }
                },
                "target": "/nodes",
            }
        }, {
            # Adds ability to read help out of assets
            "type": "object",
            "classname": "houdinihelp.hstores.AssetStore",
        }, {
            # Adds ability to read help out of shelf tools
            "type": "object",
            "classname": "houdinihelp.hstores.ShelfStore",
        },
    ]

    STATIC_DIRS = {
        "/static": "$HFS/houdini/python${PYTHON_VERSION}libs/bookish/static",
        "/hstatic": "$HFS/houdini/python${PYTHON_VERSION}libs/houdinihelp/hstatic",
        "/videos": "$HFS/houdini/help/videos",
    }
    STATIC_LOCATIONS = (
        "/static", "/hstatic", "/images", "/videos"
    )
    ARCHIVE_DIRS = {
        "/icons": "$HFS/houdini/config/Icons/icons.zip",
        "/images": "$HFS/houdini/help/images.zip",
    }


class HoudiniShdConfig(HoudniBaseConfig):
    SUPPORT_DOCUMENTS = [
        {
            "type": "mount",
            "source": "$SHH/bookish/bookish/templates",
            "target": "/templates",
        }, {
            "type": "mount",
            "source": "$SHH/bookish/bookish/grammars",
            "target": "/grammars",
        },
        {
            "type": "mount",
            "source": "$SHH/bookish/houdinihelp/templates",
            "target": "/templates",
        },
        {
            "type": "mount",
            "source": "$SHS/config/toolbar",
            "target": "/toolbar",
        },
        {
            "type": "mount",
            "source": "$SHS/icons",
            "target": "/icon_config"
        },
        {
            "type": "mount",
            "source": "$SHH/bookish/houdinihelp/hstatic",
            "target": "/hstatic"
        }
    ]

    # Storage spec for actual user documents (to be interpreted by
    # stores.store_from_spec())
    DOCUMENTS = [
        "$SHH/documents",
        {
            "type": "mount",
            "source": "$SHS/icons/",
            "target": "/icons",
        },
    ]

    STATIC_LOCATIONS = (
        "/static", "/images", "/videos", "/icons",
    )
    ARCHIVE_DIRS = {}


def read_houdini_config(cfg=None, config_file=None, root_path=".",
                        use_houdini_path=True, with_source=False):
    from bookish.config import read_config

    if os.environ.get("H_BUILD_WITH_SOURCE_HELP"):
        with_source = True
    config_obj = HoudiniShdConfig if with_source else HoudiniHfsConfig

    cfg = read_config(cfg, config_file=config_file, root_path=root_path,
                      config_obj=config_obj)

    if not config_file and use_houdini_path:
        try:
            import hou
            try:
                fname = hou.findFile("config/Help/bookish.cfg")
            except hou.OperationFailed:
                pass
            else:
                cfg.from_pyfile(fname)
        except ImportError:
            pass

    if "HOUDINI_VERSION" in os.environ:
        version = os.environ["HOUDINI_VERSION"]
    else:
        version = "1.0.234"

    cfg["HOUDINI_VERSION"] = version
    major, minor, build = version.split(".", 2)
    cfg["HOUDINI_MAJOR"] = major
    cfg["HOUDINI_MINOR"] = minor
    cfg["HOUDINI_BUILD"] = build

    return cfg




