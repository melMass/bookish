from __future__ import print_function
import os.path

# from bookish.parser.builder import build_meta, Builder
#
#
# META_NAME = "meta.bkgrammar"
#
#
# def build_grammar_modules(dirpath=None):
#     dirpath = dirpath or os.path.dirname(__file__)
#
#     names = [n for n in os.listdir(dirpath) if n.endswith(".bkgrammar")]
#     if META_NAME in names:
#         names.remove(META_NAME)
#         names.insert(0, META_NAME)
#
#     for name in names:
#         path = os.path.join(dirpath, name)
#         print("Reading", path)
#         with open(path) as f:
#             gstring = f.read()
#
#         outpath = path.replace(".bkgrammar", ".py")
#         print("Writing", outpath)
#         with open(outpath, "w") as o:
#             if name == META_NAME:
#                 build_meta(gstring, o)
#             else:
#                 Builder(file=o).build_string(gstring)
#
#
# if __name__ == "__main__":
#     build_grammar_modules()


