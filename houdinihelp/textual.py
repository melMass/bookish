from __future__ import annotations
import json
import os
import sys
from time import perf_counter
from typing import Dict, List, Optional, Sequence, Union

from flask.config import Config

from bookish import functions
from bookish.stores import expandpath, ResourceNotFoundError
from bookish.wiki.wikipages import (WikiPages, store_from_config,
                                    jinja_from_config)

from houdinihelp.hcoloring import VexLexer, OpenCLLexer, HScriptLexer
from houdinihelp.htextify import HoudiniTextifier
from houdinihelp.usd import UsdLexer

# This module bypasses the high-level API of the help system to read config,
# command, and expression help "directly" to avoid importing hou, so it can be
# used with regular Python (assuming the standard Houdini env vars and Python
# path are set up).


ver_major = ver_minor = ver_build = ""
houdini_version = os.environ.get("HOUDINI_VERSION")
if houdini_version:
    ver_major, ver_minor, ver_build = houdini_version.split(".", 2)

_HFS_MODULE_PATH = \
    "$HFS/houdini/python{}.{}libs".format(
        sys.version_info.major, sys.version_info.minor)


env_var_help = None
load_time = None


class MinConfig:
    USE_HOU = False
    HOUDINI_VERSION_MAJOR = ver_major
    HOUDINI_VERSION_MINOR = ver_minor
    HOUDINI_VERSION_BUILD = ver_build
    INDEX_DIR = expandpath("$HFS/houdini/config/Help/index")
    CACHE_DIR = "$HOUDINI_USER_PREF_DIR/config/Help/cache"
    TEXTIFY_CLASS = "houdinihelp.htextify.HoudiniTextifier"
    WIKI_STYLE = "/templates/hwiki.jinja2"
    TEMPLATE = "/templates/hpage.jinja2"
    LEXERS = {
        "vex": VexLexer,
        "ocl": OpenCLLexer,
        "hscript": HScriptLexer,
        "usd": UsdLexer,
    }
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
    ]
    DOCUMENTS = [
        "$HFS/houdini/help",
        {
            # Adds ability to read docs out of .zip files in
            # $HFS/houdini/help
            "type": "object",
            "classname": "bookish.stores.ZipTree",
            "args": {
                "dirpath": expandpath("$HFS/houdini/help"),
            }
        },
    ]


def wikiPages() -> WikiPages:
    config = Config("")
    config.from_object(MinConfig)
    store = store_from_config(config)
    jinja_env = jinja_from_config(config, store)
    return WikiPages(store, jinja_env, config)


def textify(blocks: Sequence[Dict], width=72) -> str:
    textifier = HoudiniTextifier(blocks, width=width)
    return textifier.transform()


def parseEnvVarWiki() -> Dict:
    # Returns a dictionary mapping env var names to help strings
    global env_var_help, load_time

    # The first time this function is called, it parses the /ref/env.txt wiki
    # file and stashes the help dict in the env_var_help global variable.
    # Subsequent calls simply return the cached dict.
    if env_var_help is None:
        t = perf_counter()
        pages = wikiPages()
        try:
            data = pages.json("/ref/env", extra_context={"no_page_nav": True})
        except ResourceNotFoundError:
            return {}
        section = functions.subblock_by_id(data, "env_variables")

        env_var_help = {}
        for block in functions.find_items(section, "env_variables_item"):
            name = functions.string(block.get("text")).strip()
            # Textifying everything here (instead of caching the wiki JSON and
            # textifying "on demand") only adds 0.02s, and strings use way less
            # memory than wiki JSON structures
            env_var_help[name] = textify(block.get("body"))
        load_time = perf_counter() - t

    return env_var_help


def textifiedHelp(path: str) -> Optional[str]:
    pages = wikiPages()
    try:
        root = pages.json(path, extra_context={"no_page_nav": True})
    except ResourceNotFoundError:
        return
    textifier = HoudiniTextifier(root)
    return textifier.transform()


# API

def commandTextHelp(name: str) -> Optional[str]:
    return textifiedHelp(f"/commands/{name}")


def expressionTextHelp(name: str) -> Optional[str]:
    return textifiedHelp(f"/expressions/{name}")


def configTextHelp(name: str) -> Optional[str]:
    lookup = parseEnvVarWiki()
    return lookup[name.upper()]


def allConfigTextHelp() -> Dict[str, str]:
    lookup = parseEnvVarWiki()
    # Return a copy of the dictionary with the keys in sorted order
    return {key: lookup[key] for key in sorted(lookup)}


# if __name__ == "__main__":
#     print(commandTextHelp("exit"))
#     print(expressionTextHelp("ch"))
#     print(configTextHelp("HOUDINI_AUTHOR"))
