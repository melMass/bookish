from bookish import functions
from bookish.avenue import patterns as pt
from bookish.text import textify


# var_finder = parse('body.0.text..@type="var"')
var_finder = pt.Ancestor(
    pt.Sequence([
        pt.Lookup("body"),
        pt.Lookup(0),
        pt.Lookup("text"),
    ]),
    pt.Comparison("type", "==", "var")
)


homstring_quotes = [(u'"', u'\\\\\\"')]


class HoudiniTextifier(textify.BookishTextifier):
    def root_block(self, block):
        attrs = block.get("attrs", {})
        self.pagetype = pagetype = attrs.get("type")
        body = block.get("body", ())

        if pagetype == "hscript":
            # Command help has the title at column 0 and all other text
            # indented. We'll indent everything here, and then outdent the
            # title
            with self.push(indent=4):
                self.render(body)

        elif pagetype == "expression":
            self.render_body(body)

        elif pagetype == "hompackage":
            self.emit(u'%define MODULE_DOCSTRING /**/ "', top=1)
            with self.push(replacements=homstring_quotes):
                self.render(body)
            self.emit(u'" %enddef', bottom=1)

        elif pagetype in (u"homclass", u"homfunction", u"hommodule",
                          "pypackage", "pymodule", "pyfunction", "pyclass"):
            cppname = attrs.get("cppname")
            if cppname:
                self.emit(u'%%feature("docstring") %s "' % cppname, wrap=False)

                # Render everything EXCEPT @methods or @functions sections
                special_sections = []
                with self.push(replacements=homstring_quotes):
                    for subblock in body:
                        if (
                            subblock.get("role") == "section" and
                            subblock.get("id") in ("methods", "functions")
                        ):
                            special_sections.append(subblock)
                        else:
                            self.render(subblock)

                self.emit(u'";')

                for subblock in special_sections:
                    itemtype = subblock["id"] + "_item"
                    for itemblock in functions.find_items(subblock, itemtype):
                        self._homfn(itemblock)

        elif pagetype == u"env":
            section = functions.first_subblock_of_type(block, "env_variables_section")
            for item in functions.find_items(section, "env_variables_item"):
                self.render(item)
        else:
            self.render(body)

    def title_block(self, block):
        if self.pagetype == "hscript":
            self.emit_block_text(block, indent=-4)
            self._replaced_by()
        elif self.pagetype == "expression":
            name = functions.string(block.get("text"))
            # Pull out the usage section
            usage = functions.subblock_by_id(self.root, "usage")
            if usage and "body" in usage and usage["body"]:
                firstb = usage["body"][0]
                varnames = [functions.string(span) for span
                            in functions.find_spans_of_type(firstb, "var")]
                self.emit(name + u" " + u" ".join(varnames))
            else:
                self.emit(name)
            self._replaced_by()
        else:
            self.render_super(block)
            # self._replaces()

    def summary_block(self, block):
        self.emit_block_text(block, top=1, bottom=1)

    def usage_block(self, block):
        self.emit_block_text(block)
        self.render_body(block)

    def usage_group_block(self, block):
        body = block.get("body", ())
        heading = "USAGE" if len(body) == 1 else "USAGES"
        self.emit(heading, top=1)
        self.render_body(body, bottom=1, indent=2)

    def h_block(self, block):
        attrs = block.get("attrs")
        if attrs and "super_path" in attrs:
            return
        super(HoudiniTextifier, self).h_block(block)

    def _homfn(self, block):
        attrs = block.get("attrs", {})
        status = attrs.get("status")
        cppname = attrs.get("cppname")
        if cppname and status != u"ni":
            self.emit(u'%%feature("docstring") %s "' % cppname, wrap=False)
            with self.push(replacements=homstring_quotes):
                self.emit(functions.string(block.get("text")), bottom=1)
                with self.push(left=4):
                    self.render(block.get("body", ()))
            self.emit(u'";')
        cppname = attrs.get("cppname")
        if cppname:
            self.emit(u'%%feature("docstring") %s "' % cppname, wrap=False)
            with self.push(replacements=homstring_quotes):
                self.emit(functions.string(block.get("text")), bottom=1)
                with self.push(left=4):
                    self.render(block.get("body", ()))
            self.emit(u'";')

    # def _replaces(self):
    #     repls = self.root.get("attrs", {}).get("replaces")
    #     print("repls=", repr(repls))
    #     if repls:
    #         with self.push(bottom=1):
    #             self.emit(u"Replaces", top=1, upper=True)
    #             with self.push(indent=4):
    #                 for repl in repls:
    #                     self.emit(repl["title"], first="- ",
    #                               rest="  ")

    def _replaced_by(self):
        repls = self.root.get("replacedby")
        if repls:
            with self.push(bottom=1):
                self.emit(u"Python Equivalent", top=1, upper=True)
                with self.push(indent=4):
                    for repl in repls:
                        self.emit(repl["title"], first="- ", rest="  ")


class HoudiniFormattedTextifier(HoudiniTextifier):
    def var_span(self, span):
        return u"<i>" + self.render_text(span) + u"</i>"

    def strong_span(self, span):
        return u"<b>" + self.render_text(span) + u"</b>"

    def em_span(self, span):
        return u"<i>" + self.render_text(span) + u"</i>"

    def code_span(self, span):
        return u"<tt>" + self.render_text(span) + u"</tt>"
