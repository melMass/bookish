from __future__ import print_function
from collections import OrderedDict
import os.path
import re


shifted = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
    "&": "7", "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[",
    "}": "]", "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
}

xlate = {
    "LeftArrow": "Left",
    "RightArrow": "Right",
    "UpArrow": "Up",
    "DownArrow": "Down",
    "PageUp": "PgUp",
    "PageDown": "PgDn",
}

key_expr = re.compile(".[^+]*")


def parse_key(string):
    return [k.strip() for k in string.split("+")]


def hotkey_to_wiki(hotkey):
    shift = False
    presses = []
    pos = 0
    while pos < len(hotkey):
        m = key_expr.match(hotkey, pos)
        if not m:
            raise Exception("No match in %r at %s" % (hotkey, pos))
        key = m.group(0).strip()  # type: str

        if key in shifted:
            shift = True
            presses.append(shifted[key])
        elif key == "Shift":
            shift = True
        elif key in xlate:
            presses.append(xlate[key])
        elif key.isalpha() and key.isupper():
            shift = True
            presses.append(key)
        elif key.isalpha() and key.islower():
            presses.append(key.upper())
        else:
            presses.append(key)

        pos = m.end()
        if pos < len(hotkey):
            assert hotkey[pos] == "+"
            pos += 1

    if shift:
        if "Ctrl" in presses:
            ctrlp = presses.index("Ctrl")
            presses.insert(ctrlp, "Shift")
        elif "Alt" in presses:
            altp = presses.index("Alt")
            presses.insert(altp, "Shift")
        else:
            presses.insert(0, "Shift")

    return presses


# Houdini hotkey file parser

class HotkeyFileParser:
    ctx_exp = re.compile(r'HCONTEXT\s+([^\t ]+)\s+"([^"]+)"\s+"([^"]+)"')
    key_exp = re.compile(r'([^ \t]+)\s+"([^"]+)"\s+"([^"]+)"(\s+\S+)*')

    def __init__(self):
        self.contexts = {}
        self.ctx_by_name = {}
        self.keycount = 0

    @staticmethod
    def _get_ctx(ctx, parts):
        key = parts.pop(0)
        ctx = ctx.setdefault(key, {})
        if parts:
            return HotkeyFileParser._get_ctx(ctx, parts)
        else:
            return ctx

    def _process_line(self, filename, line):
        contexts = self.contexts
        ctx_by_name = self.ctx_by_name

        ctx_match = self.ctx_exp.match(line)
        if ctx_match:
            name, label, desc = ctx_match.groups()
            ctx = self._get_ctx(contexts, name.split("."))
            ctx_by_name[name] = ctx
            ctx["_file"] = filename
            ctx["_label"] = label
            ctx["_desc"] = desc
            return

        key_match = self.key_exp.match(line)
        if key_match:
            name, label, desc, keys = key_match.groups()
            context_name, action_name = name.rsplit(".", 1)
            action_dict = OrderedDict()
            action_dict["symbol"] = action_name
            action_dict["label"] = label
            action_dict["description"] = desc
            if keys:
                action_dict["keys"] = keys.split()

            ctx = self._get_ctx(contexts, name.split(".")[:-1])
            actions = ctx.setdefault("_actions", [])
            actions.append(action_dict)
            self.keycount += 1

    def parse_file(self, filepath):
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//"):
                    continue

                self._process_line(filepath, line)

    def parse_dir(self, dirpath):
        for filename in os.listdir(dirpath):
            if not (filename == "h" or filename.startswith("h.")):
                continue
            filepath = os.path.join(dirpath, filename)
            self.parse_file(filepath)

    def json_obj(self):
        contexts = []
        for ctxname in sorted(self.ctx_by_name):
            ctx = self.ctx_by_name[ctxname]
            ctx_dict = OrderedDict()
            ctx_dict["symbol"] = ctxname
            ctx_dict["label"] = ctx["_label"]
            ctx_dict["description"] = ctx["_desc"]
            ctx_dict["actions"] = ctx.get("_actions", [])
            contexts.append(ctx_dict)

        return {
            "contexts": contexts,
        }

    def json_text(self):
        import json

        return json.dumps(self.json_obj(), sort_keys=False)

    def print_json(self):
        import json
        import sys

        json.dump(self.json_obj(), sys.stdout, indent=4, sort_keys=False)


def hotkey_json_from_file(filepath):
    parser = HotkeyFileParser()
    parser.parse_file(filepath)
    return parser.json_obj()


# Find all action definitions in help files

def find_actions(pages):
    from bookish import functions

    store = pages.store
    for path in store.list_all():
        if not path.endswith(".txt"):
            continue

        # Peeks at the file contents and check that it has the string #action:
        # before we try to parse it, as a hacky optimization
        content = store.content(path)
        if "#action:" not in content:
            continue

        json = pages.json(path)
        for block in functions.find_with_attr(json, "action"):
            attrs = block["attrs"]
            actionid = attrs["action"]
            if actionid.startswith("."):
                raise Exception("Bad context %r in %s" % (actionid, path))
            label = functions.string(block.get("text"))
            desc = functions.first_subblock_string(block)
            yield actionid, label, desc, path


def actions_to_json(actions):
    ctxs = {}
    for actionid, label, desc, path in actions:
        contextid, actionname = actionid.rsplit(".", 1)
        if contextid.startswith("."):
            raise Exception("Bad context: %r" % contextid)
        if contextid not in ctxs:
            ctxdict = OrderedDict()
            ctxdict["symbol"] = contextid
            ctxdict["actions"] = []
            ctxdict["helppath"] = path
            ctxs[contextid] = ctxdict

        actiondict = OrderedDict()
        actiondict["symbol"] = actionname
        actiondict["label"] = label
        actiondict["description"] = desc

        ctxs[contextid]["actions"].append(actiondict)

    return {
        "contexts": [ctxs[ctxid] for ctxid in sorted(ctxs)],
    }


def hotkey_json_from_docs(pages):
    return actions_to_json(find_actions(pages))


if __name__ == "__main__":
    import sys
    filepath = sys.argv[1]
    parser = HotkeyFileParser()
    parser.parse_file(filepath)
    parser.print_json()




