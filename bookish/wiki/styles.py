# Copyright 2014 Matt Chaput. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#    1. Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#
#    2. Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY MATT CHAPUT ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO
# EVENT SHALL MATT CHAPUT OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are
# those of the authors and should not be interpreted as representing official
# policies, either expressed or implied, of Matt Chaput.

import inspect
import weakref

import jinja2
from jinja2 import environment
from markupsafe import escape

from bookish import paths, util, functions


class JinjaStoreLoader(jinja2.BaseLoader):
    """
    Jinja template loader that loads templates from a Bookish storage object.
    """

    def __init__(self, store, prefix="/templates/"):
        self.store = weakref.ref(store)
        self.prefix = prefix

    def get_source(self, environment, template_path):
        if not paths.is_abs(template_path):
            template_path = self.prefix + template_path
        store = self.store()
        if not store:
            raise Exception(f"No store to load {template_path}")
        content = store.content(template_path)
        filepath = store.file_path(template_path)
        lastmod = store.last_modified(template_path)
        uptodate = lambda: store.last_modified(template_path) == lastmod
        return content, filepath, uptodate

    def list_templates(self, extensions=None, filter_func=None):
        for path in self.store().list_dir(self.prefix):
            if filter_func and filter_func(path):
                yield path
            elif extensions and paths.extension(path) in extensions:
                yield path


class Stylesheet(object):
    def __init__(self, env, templatename, index_page_name):
        self.env = env
        self.templatename = templatename
        self.index_page_name = index_page_name

        # Cache for compiled Avenue pattern objects
        self._patterns = {}

    def __repr__(self):
        return "<Stylesheet %r>" % (self.templatename,)

    @staticmethod
    def default_rule(jinctx, obj, render):
        # Default action for blocks that don't have an associated rule
        if isinstance(obj, (list, tuple)):
            return functions.string(obj)
        elif isinstance(obj, dict):
            return "".join((render(jinctx, obj.get("text", ())),
                            render(jinctx, obj.get("body", ()))))
        else:
            return escape(functions.string(obj))

    def context_and_function(self, basepath, jsondata, extras=None):
        """
        Returns a Jinja context function you can use to transform a JSON
        document using the rules contained in this style's template.
        """

        # import time
        # t = time.time()

        template = self.env.get_template(self.templatename)
        namespace = {}

        # Create the render function
        @jinja2.pass_context
        def render(jinctx, obj):
            if isinstance(obj, dict):
                rule = None
                objtype = obj.get("type")
                objrole = obj.get("role")

                # If this is a link, look for a specific rule based on the
                # link scheme
                if objtype == "link" and "scheme" in obj:
                    macroname = "%s_link_rule" % obj["scheme"]
                    if macroname in namespace:
                        rule = namespace[macroname]

                if rule is None:
                    # Look for a rule named <type>_rule, then <role>_rule
                    for prefix in (objtype, objrole):
                        if not prefix:
                            continue

                        macroname = "%s_rule" % prefix
                        if macroname in namespace:
                            rule = namespace[macroname]
                            break

                if rule is None:
                    if "default" in namespace:
                        rule = namespace["default"]
                    else:
                        return self.default_rule(jinctx, obj, render)

                return rule(obj)

            elif isinstance(obj, (list, tuple)) or inspect.isgenerator(obj):
                return functions.string(render(jinctx, o) for o in obj)
            else:
                return escape(functions.string(obj))

        # Create a new Jinja context
        variables = {
            "render": render,
            "docroot": jsondata,
        }
        if extras:
            variables.update(extras)

        jinjactx = template.new_context(vars=variables)
        # Run the style template to evaluate the rule definitions
        list(template.root_render_func(jinjactx))

        # Now that we've run the template, we know which macros it had and which
        # modules it imported... add all macros to the "namespace" dict
        queue = [jinjactx.vars]
        while queue:
            d = queue.pop(0)
            for k, v in d.items():
                if k.endswith("_rule") and k not in namespace:
                    namespace[k] = v
                elif isinstance(v, environment.TemplateModule):
                    queue.append(v.__dict__)

        # print(time.time() - t)
        # print("ns=", namespace)
        return jinjactx, render

    def render(self, basepath, jsondata):
        ctx, render_fn = self.context_and_function(basepath, jsondata)
        return render_fn(ctx, jsondata)
