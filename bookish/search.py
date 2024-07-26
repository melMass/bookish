from __future__ import print_function
import errno
import logging
import os.path
import re

import whoosh
from whoosh import analysis, columns, fields, index, qparser, query, sorting
from whoosh.index import LockError
from bookish import compat, paths, functions, util
from bookish.stores import ResourceNotFoundError
from bookish.wiki import langpaths


HOST_EXITING = False
IS_WHOOSH3 = whoosh.__version__[0] >= 3


default_logger = logging.getLogger(__name__)
default_logger.setLevel(logging.INFO)
sh = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
sh.setFormatter(formatter)
default_logger.addHandler(sh)


text_ana = (
    analysis.RegexTokenizer(expression=r"\w+")
    | analysis.IntraWordFilter(mergewords=True, mergenums=True)
    | analysis.LowercaseFilter()
    | analysis.StopFilter()
    | analysis.StemFilter(lang="en")
)


default_fields = {
    "path": fields.ID(stored=True, unique=True),
    "parent": fields.KEYWORD,
    "content": fields.TEXT(analyzer=text_ana),
    "title": fields.TEXT(analyzer=text_ana, stored=True, sortable=True),
    "category": fields.ID(sortable=columns.RefBytesColumn()),
    "subject": fields.STORED,
    "icon": fields.STORED,
    "sortkey": fields.ID(sortable=True),
    "grams": fields.NGRAMWORDS(minsize=2),
    "type": fields.KEYWORD(stored=True),
    "tags": fields.KEYWORD(stored=True),
    "modified": fields.DATETIME(stored=True),
    "links": fields.KEYWORD,
    "container": fields.STORED,
    "isindex": fields.BOOLEAN,
    "lang": fields.ID,
    "anchor": fields.KEYWORD,
}

dynamic_fields = {
    "*_anchor": fields.ID,
    "*_parent": fields.KEYWORD,
}


def become_instant(andq):
    qs = []
    for subq in andq:
        if isinstance(subq, query.Term) and subq.field() == "content":
            qs.append(query.Term("instant", subq.text))
        else:
            qs.append(subq)
    return query.And(qs)


def combine_readers(readers):
    from whoosh import reading

    rs = []
    for r in readers:
        if r.is_atomic():
            rs.append(r)
        else:
            rs.extend(r.readers)

    if rs:
        if len(rs) == 1:
            return rs[0]
        else:
            return reading.MultiReader(rs)

    raise index.EmptyIndexError


class Searchables(object):
    index_page_name = None

    @staticmethod
    def _get_block_text(body, typename):
        if body:
            for block in body:
                if block.get("type") == typename:
                    return functions.string(block.get("text"))
        return ""

    @staticmethod
    def _get_path_attr(root, path, attrs, name):
        value = attrs.get(name)
        if value:
            return paths.join(path, value)

    def schema(self):
        schema = fields.Schema(**default_fields)
        for fieldname, fieldtype in dynamic_fields.items():
            schema.add(fieldname, fieldtype, glob=True)
        return schema

    def _should_index_document(self, pages, path, root, block):
        attrs = block.get("attrs")
        mode = None
        if attrs:
            if "type" in attrs:
                if attrs["type"].strip() == "include":
                    return False
            if "index" in attrs:
                if attrs["index"].lower().strip() == "no":
                    return False

            mode = attrs.get("index")

        if mode != "no":
            return block.get("type") == "root" or mode == "document"

    def _should_index_block(self, block):
        attrs = block.get("attrs")
        mode = attrs.get("index") if attrs else None
        return mode != "no"

    def documents(self, pages, path, root, options, cache):
        docs = []

        if self._should_index_document(pages, path, root, root):
            self._block_to_doc(pages, path, root, root, docs, cache)
        return docs

    def _block_to_doc(self, pages, path, root, block, docs, cache,
                      recurse=True):
        if recurse:
            gen = self._flatten_with_docs(pages, path, root, block, docs, cache)
        else:
            gen = self._flatten(block)
        text = " ".join(gen)
        docs.append(self._make_doc(pages, path, root, block, text, cache))

    def _flatten(self, block):
        if not self._should_index_block(block):
            return

        if "text" in block:
            yield functions.string(block["text"])

        if "body" in block:
            for subblock in block["body"]:
                for text in self._flatten(subblock):
                    yield text

    def _flatten_with_docs(self, pages, path, root, block, docs, cache):
        if not self._should_index_block(block):
            return

        if "text" in block:
            yield functions.string(block["text"])

        if "body" in block:
            for subblock in block["body"]:
                if self._should_index_document(pages, path, root, subblock):
                    self._block_to_doc(pages, path, root, subblock, docs,
                                       cache, recurse=False)
                else:
                    for text in self._flatten_with_docs(pages, path, root,
                                                        subblock, docs, cache):
                        yield text

    def _get_title(self, block):
        if block.get("type") == "root":
            return functions.string(block.get("title")).strip()
        else:
            return functions.string(block.get("text")).strip()

    def _make_doc(self, pages, path, root, block, text, cache):
        attrs = block.get("attrs", {})
        blocktype = block.get("type")
        body = block.get("body")
        is_root = blocktype == "root"

        # If a title was not passed in: if this is the root, look for a title
        # block, otherwise use the block text
        title = self._get_title(block) or paths.basename(path)

        container = False
        # path = paths.basepath(path)
        if is_root:
            # Store a boolean if this page has subtopics
            subtopics = functions.subblock_by_id(block, "subtopics")
            container = subtopics and bool(subtopics.get("body"))
        else:
            blockid = functions.block_id(block)
            path = "%s#%s" % (path, blockid)

        # Look for a summary block
        summary = self._get_block_text(body, "summary")

        # Look for tags in the page attributes
        tags = attrs.get("tags", "").strip().replace(",", "") or None

        # Find outgoing links
        outgoing = []
        for link in functions.find_links(block):
            val = link.get("value")
            val, _ = paths.split_fragment(val)
            if val:
                outgoing.append(pages.full_path(path, val))
        outgoing = " ".join(outgoing)

        doctype = attrs.get("type")
        pagelang = pages.page_lang(path)

        d = {
            "path": path,
            "status": attrs.get("status"),
            "category": attrs.get("category", "_"),
            "content": functions.string(text),
            "title": title,
            "sortkey": attrs.get("sortkey") or title.lower().replace(" ", ""),
            "summary": summary,
            "grams": title,
            "type": doctype,
            "tags": tags,
            "icon": attrs.get("icon"),
            "links": outgoing,
            "container": container,
            "parent": self._get_path_attr(block, path, attrs, "parent"),
            "isindex": is_root and paths.basename(path) == self.index_page_name,
            "lang": pagelang,
            "anchor": attrs.get("anchor"),
            # "bestbet": attrs.get("bestbet"),
        }

        # Let the store contribute extra fields if it wants to
        if is_root:
            extra = pages.store.extra_fields(path)
            if extra:
                d.update(extra)

        # Add dynamic anchors
        for aname in attrs:
            if aname.endswith("_anchor") or aname.endswith("_parent"):
                d[aname] = attrs[aname]

        # Let the wiki pipeline modify the indexed document
        pages.process_indexed_doc(block, d, cache)

        return d


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno != errno.EEXIST or not os.path.isdir(path):
            raise


class WhooshIndexer(object):
    def __init__(self, indexdir, searchables, options=None, create=True,
                 indexname=None, logger=None):
        self.indexdir = indexdir
        self.searchables = searchables
        self.options = options or {}
        self.cache = {}
        self.logger = logger or default_logger

        schema = self.searchables.schema()
        if not index.exists_in(indexdir, indexname=indexname) and create:
            mkdir_p(indexdir)
            self.index = index.create_in(indexdir, schema=schema,
                                         indexname=indexname)
        else:
            self.index = index.open_dir(indexdir, schema=schema,
                                        indexname=indexname)

    @staticmethod
    def index_exists_in(indexdir, indexname=None):
        return index.exists_in(indexdir, indexname=indexname)

    @staticmethod
    def _sanitize_doc(doc):
        for key, value in doc.items():
            if isinstance(value, compat.bytes_type):
                doc[key] = value.decode("ascii")

    def set_option(self, name, value):
        self.options[name] = value

    def close(self):
        self.index.close()

    def reader(self):
        return self.index.reader()

    def searcher(self, overlay=True):
        try:
            from houdinihelp.api import ram_index
        except ImportError:
            ram_index = None

        s = self.index.searcher()
        if overlay and ram_index and not ram_index.is_empty():
            readers = [r for r, _ in s.reader().leaf_readers()]
            ram_reader = ram_index.reader()
            readers.append(ram_reader)
            mr = whoosh.reading.MultiReader(readers)
            if IS_WHOOSH3:
                cls = whoosh.searching.MultiSearcher
                w = s.weighting
                ix = s.index()
            else:
                cls = whoosh.searching.Searcher
                w = s.weighting
                ix = s._ix
            s = cls(mr, weighting=w, fromindex=ix)

        return WhooshSearcher(s)

    def query(self):
        return self.searcher().query()

    def _find_files(self, pages, reader, clean, ignore_paths=()):
        # t = compat.perf_counter()
        store = pages.store

        existing = set()
        for p in store.list_all():
            if HOST_EXITING:
                return None, None, None
            if pages.is_wiki(p):
                bp = paths.basepath(p)
                if not bp in ignore_paths:
                    existing.add(bp)
        self.logger.debug("Existing paths=%r", existing)

        if clean:
            new = existing
            changed = set()
            deleted = set()
        else:
            # Read all the stored field dicts from the index and build a
            # dictionary mapping paths to their last indexed mod time
            modtimes = {}
            for did in reader.all_doc_ids():
                if HOST_EXITING:
                    return None, None, None
                fs = reader.stored_fields(did)
                p = fs["path"]
                if "#" in p:
                    continue

                try:
                    modtime = fs["modified"]
                except KeyError:
                    continue

                modtimes[p] = modtime
                self.logger.debug("%s last modified %s", p, modtime)

            indexedpaths = set(modtimes)
            new = existing - indexedpaths
            deleted = indexedpaths - existing
            both = existing - new - deleted
            self.logger.debug("Both=%r", both)

            changed = set()
            for path in sorted(both):
                ix_mod = modtimes[path]
                try:
                    store_mod = store.last_modified(pages.source_path(path))
                except ResourceNotFoundError:
                    # This shouldn't happen... it seems to mean the file was
                    # deleted between the list_all() above and here. :( We won't
                    # try to move the file into the deleted pile, but by setting
                    # this to None it should prevent it from being re-indexed at
                    # least.
                    store_mod = None
                self.logger.debug("path=%s, store (%s) > index (%s)= %s",
                                  path, store_mod, ix_mod,
                                  bool(store_mod and store_mod > ix_mod))
                if store_mod and store_mod > ix_mod:
                    self.logger.info("%s: store=%s > index=%s", path, store_mod,
                                     ix_mod)
                    changed.add(path)

        # print("find files=", compat.perf_counter() - t)
        return new, changed, deleted

    def dump(self, pages):
        idx = self.index

        def print_set(s):
            for path in sorted(s):
                print("    ", path)

        with idx.reader() as r:
            new, changed, deleted = self._find_files(pages, r, False)
            print("NEW", len(new))
            print_set(new)
            print("CHANGED", len(changed))
            print_set(changed)
            print("DELETED", len(deleted))
            print_set(deleted)

    def documents(self, pages, path):
        if not pages.exists(path):
            return

        modtime = pages.last_modified(path)
        jsondata = pages.json(path, postprocess=False)

        docs = self.searchables.documents(pages, path, jsondata, self.options,
                                          self.cache)
        for doc in docs:
            if HOST_EXITING:
                return
            if doc.get("path") == path:
                doc["modified"] = modtime
            yield doc

    def create(self):
        if not os.path.exists(self.indexdir):
            os.mkdir(self.indexdir)

    def writer(self, **kwargs):
        return self.index.writer(**kwargs)

    def update(self, pages, clean=False, optimize=False, **kwargs):
        if clean:
            schema = self.searchables.schema()
            self.index = index.create_in(self.indexdir, schema=schema)
        idx = self.index

        self.logger.info("Indexing %s files to %s, optimized=%s",
                         ("all" if clean else "changed"), self.indexdir,
                         optimize)

        with idx.writer(**kwargs) as w:
            w.optimize = optimize

            didsomething, t, doccount, pagecount = self.update_with(
                w, pages, clean=clean
            )

            if IS_WHOOSH3 and not didsomething:
                w.cancel()

        if didsomething:
            self.logger.info("Indexed %d docs from %d pages in %.06f seconds",
                             doccount, pagecount, compat.perf_counter() - t)
        return didsomething

    def update_with(self, writer, pages, clean=False, overlay=False):
        doccount = 0
        pagecount = 0
        ignorepaths = ()
        if overlay:
            ignorepaths = set(p.decode("utf-8") for p
                              in self.reader().lexicon("path")
                              if not b"#" in p)

        t = compat.perf_counter()
        new, changed, deleted = self._find_files(pages, writer.reader(), clean,
                                                 ignore_paths=ignorepaths)
        if HOST_EXITING:
            return

        self.logger.debug("New paths=%r", new)
        self.logger.debug("Changed paths=%r", changed)
        self.logger.debug("Deleted paths-=%r", deleted)

        didsomething = False
        if new or changed or deleted:
            if deleted:
                self.delete_paths_with(writer, sorted(changed | deleted))

            update_paths = sorted(new | changed)
            didupdate, pagecount, doccount = self.index_paths_with(
                writer, pages, update_paths, needs_delete=changed
            )
            didsomething = deleted or didupdate

        if HOST_EXITING:
            return
        if didsomething:
            self.logger.info("Committing index changes")
        else:
            self.logger.info("No changes to commit")

        return didsomething, t, doccount, pagecount

    def index_paths_with(self, writer, pages, pathlist, needs_delete=None):
        didsomething = False
        pagecount = 0
        doccount = 0
        # archive = {}

        for path in pathlist:
            if HOST_EXITING:
                return False, 0, 0
            # self.logger.info("Updating %s", path)
            added = False

            if needs_delete is None or path in needs_delete:
                self.logger.info("Deleting path %s", path)
                writer.delete_by_term("path", path)
                writer.delete_by_query(query.Prefix("path", path + "#"))
                didsomething = True

            for doc in self.documents(pages, path):
                # archive[doc["path"]] = doc
                if HOST_EXITING:
                    return None, None, None

                self._sanitize_doc(doc)
                self.logger.info("Indexing %s", doc["path"])
                try:
                    writer.add_document(**doc)
                except ValueError:
                    self.logger.error("Error indexing %r", doc)
                    raise

                added = True
                doccount += 1

            if added:
                pagecount += 1
                didsomething = True
            else:
                self.logger.debug("No indexables in %s", path)

        # import json
        # from datetime import datetime
        # with open("/Users/matt/dev/src/houdini/help/build/archive.json", "w", encoding="utf-8") as f:
        #     def serializer(value):
        #         if isinstance(value, datetime):
        #             return value.isoformat()
        #     json.dump(archive, f, default=serializer)

        return didsomething, pagecount, doccount

    def delete_paths_with(self, writer, pathlist):
        import time
        t = time.time()
        for path in pathlist:
            if HOST_EXITING:
                return None, None, None
            self.logger.info("Deleting %s from index", path)
            writer.delete_by_term("path", path)
            writer.delete_by_query(query.Prefix("path", path + "#"))
        self.logger.info("")


class WhooshSearcher(object):
    def __init__(self, searcher):
        self.searcher = searcher
        self.limit = None
        self.sortedby = None
        self._lookup_cache = {}
        self._tag_cache = {}

    @staticmethod
    def _to_key(fields):
        return tuple(sorted(fields.items()))

    def up_to_date(self):
        return self.searcher.up_to_date()

    def has_field(self, fieldname):
        return fieldname in self.searcher.schema

    def lexicon(self, fieldname):
        searcher = self.searcher
        field = searcher.schema[fieldname]
        return (field.from_bytes(btext)
                for btext in searcher.lexicon(fieldname))

    def term_exists(self, fieldname, text):
        return (fieldname, text) in self.searcher.reader()

    def query(self):
        return WhooshQuery(self.searcher)

    def document(self, **fields):
        if len(fields) == 1 and "path" in fields:
            key = fields["path"]
            try:
                return self._lookup_cache[key]
            except KeyError:
                pass
            t = util.perf_counter()
            result = self.searcher.document(**fields)
            self._lookup_cache[key] = result
        else:
            result = self.searcher.document(**fields)
        return result

    def tagged_documents(self, tagname, pagetype=None):
        key = tagname, pagetype
        tcache = self._tag_cache
        if key in tcache:
            result = tcache[key]
        else:
            docs = self.documents(tags=tagname, type=pagetype)
            result = sorted(docs, key=lambda d: d.get("path", ""))
            tcache[key] = result
        return result

    def documents(self, **fields):
        return self.searcher.documents(**fields)

    def search(self, *args, **kwargs):
        return self.searcher.search(*args, **kwargs)

    def all_stored_fields(self):
        return self.searcher.all_stored_fields()

    def group_hits(self, docnums):
        s = self.searcher
        return [s.stored_fields(docnum) for docnum in docnums]


class WhooshQuery(object):
    shortcut_exp = re.compile(r"(^|\s)!([A-Za-z0-9]+)($|\s)")

    def __init__(self, searcher):
        self.searcher = searcher
        self.q = None
        self.limit = None
        self.sortedby = None
        self.groupedby = None
        self._shortcut_regexes = {}

    def __repr__(self):
        return "<%s %r>" % (type(self).__name__, self.q)

    def parse(self, qstring, field=None):
        schema = self.searcher.schema
        if field:
            qp = qparser.QueryParser(field, schema)
        else:
            qp = qparser.MultifieldParser(["title", "content"], schema)
        return qp.parse(qstring)

    def _make_kw_query(self, fields):
        terms = []
        for fieldname, value in fields.items():
            terms.append(query.Term(fieldname, value))
        if len(terms) == 1:
            return terms[0]
        else:
            return query.And(terms)

    def make_query(self, qstring=None, field=None, **fields):
        if qstring is not None:
            q = self.parse(qstring, field)
        elif fields:
            q = self._make_kw_query(fields)
        else:
            raise Exception("Must give a query string or use keyword args")
        return q

    def set(self, qstring, **fields):
        self.q = self.make_query(qstring, **fields)

    def set_limit(self, limit):
        self.limit = limit

    def add_sort_field(self, fieldname, reverse=False):
        if self.sortedby is None:
            self.sortedby = sorting.MultiFacet()
        self.sortedby.add_field(fieldname, reverse)

    def set_group_field(self, fieldname, overlap):
        self.groupedby = sorting.FieldFacet(fieldname, allow_overlap=overlap)

    def search(self, lang=None):
        q = self.q.normalize()

        lang_filter = None
        if lang:
            lang_filter = self.make_query(lang, "lang")

        hits = self.searcher.search(q, limit=self.limit, sortedby=self.sortedby,
                                    groupedby=self.groupedby,
                                    filter=lang_filter)
        return hits

    def expand_shortcuts(self, qstring, shortcuts):
        changed = False
        for shortcut in shortcuts:
            key = shortcut["shortcut"]
            if key in self._shortcut_regexes:
                exp = self._shortcut_regexes[key]
            else:
                pattern = r"(^|(?<=\s))!%s($|(?=\s))" % re.escape(key)
                exp = self._shortcut_regexes[key] = re.compile(pattern)

            if exp.search(qstring):
                qstring = exp.sub(shortcut["query"], qstring)
                changed = True
        return qstring, changed

    def results(self, pages, qstring, cat_order, category=None, shortcuts=None,
                limit=None, cat_limit=5, require=None, lang=None, sequence=0):
        from whoosh.util import now

        contentfield = "content"
        t = now()
        s = self.searcher
        limit = limit or self.limit
        showall = False

        if shortcuts:
            qstring, showall = self.expand_shortcuts(qstring, shortcuts)

        all_q = self.make_query(qstring, contentfield)

        if require:
            require_q = self.make_query(require, contentfield)
            all_q = query.Require(all_q, require_q)

        lang_filter = None
        if lang:
            lang_filter = self.make_query(lang, "lang")

        # Find "instant" results
        instants = []
        do_inst = False
        inst_q = self.make_query(qstring, "instant")
        if isinstance(inst_q, query.Term) and inst_q.field() == "instant":
            # The query is one word, search for that word in instants
            do_inst = True
        elif isinstance(inst_q, query.CompoundQuery):
            # How many of the subqueries are terms in the content field?
            tqs = [subq for subq in inst_q.children()
                   if isinstance(subq, query.Term) and
                   subq.field() == "instant"]
            # If only one, run a query where that word is in the instant field
            do_inst = len(tqs) == 1

        if do_inst:
            for hit in s.search(inst_q, filter=lang_filter):
                d = hit.fields()
                # Need to get "category" separately because it's in a column;
                # should fix this in Whoosh
                d["category"] = hit["category"]
                instants.append(d)

            # Sort the instant results by the category order in the config
            def keyfn(d):
                try:
                    return cat_order.index(d.get("category", "_"))
                except ValueError:
                    # A page's category is not explicitly listed in the category
                    # order configuration
                    return 9999
            instants.sort(key=keyfn)

        grams_groups = None
        grams_q = self.make_query(qstring, "grams")
        if IS_WHOOSH3:
            all_terms = grams_q.terms
        else:
            all_terms = grams_q.iter_all_terms
        if any(fn == "grams" for fn, _ in all_terms()):
            try:
                grams_r = s.search(grams_q, limit=limit, groupedby="category",
                                   filter=lang_filter)
            except query.QueryError:
                pass
            else:
                grams_groups = grams_r.groups()

        all_r = s.search(all_q, limit=limit, groupedby="category",
                         filter=lang_filter)
        all_groups = all_r.groups()

        # OK, this is complicated... we want to present the categories in the
        # order defined in cat_order, BUT we want categories that have grams
        # matches to come before categories that only have content matches
        final_order = []
        if grams_groups:
            # Add categories in grams_groups in the order defined by cat_order
            for cat in cat_order:
                if cat in grams_groups:
                    final_order.append(cat)
            # Add any categories in grams_groups that aren't in cat_order
            final_order.extend(cat for cat in sorted(grams_groups)
                               if cat not in cat_order)

        seen = set(final_order)
        # Add categories in all_groups in the order defined by cat_order, IF
        # they weren't already added in the previous step
        for cat in cat_order:
            if cat in all_groups and cat not in seen:
                final_order.append(cat)
        # Add any categories in all_groups that weren't added in the previous
        # steps
        final_order.extend(cat for cat in sorted(all_groups)
                           if cat not in cat_order and cat not in seen)

        # If there's only one category, there's no point in cutting it off,
        # just show all hits
        showall = showall or len(final_order) == 1

        # For each category, pull out the docnums and get their stored fields
        length = 0
        categories = []
        for cat in final_order:
            # Combine the docnums for this category from grams and all
            docnums = []
            seen = set()
            if grams_groups:
                for docnum in grams_groups.get(cat, ()):
                    docnums.append(docnum)
                    seen.add(docnum)

            for docnum in all_groups.get(cat, ()):
                if docnum not in seen:
                    docnums.append(docnum)
                    seen.add(docnum)

            # If the number of hits is exactly the limit + 1, then there's no
            # point showing a "show more" line instead of that one extra hit,
            # so just increase the limit in that case
            if len(docnums) == cat_limit + 1:
                cutoff = len(docnums)
            else:
                cutoff = cat_limit

            if cat != category and not showall and len(docnums) > cutoff:
                docnums = docnums[:cutoff]

            length += len(seen)
            docs = [s.stored_fields(docnum) for docnum in docnums]
            categories.append((cat, docs, len(seen)))

        sent = now()
        runtime = sent - t
        # print("Results", qstring, runtime, sequence)
        return {
            "qstring": qstring,
            "instants": instants,
            "category": category,
            "categories": categories,
            "length": length,
            "limit": limit,
            "hitobj": all_r,
            "hits": [hit.fields() for hit in all_r],
            "sequence": sequence,
            "runtime": runtime,
        }

