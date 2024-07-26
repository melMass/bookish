# Copyright 2017 Matt Chaput. All rights reserved.
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

from bookish import util


class ParserError(Exception):
    pass


class ParserContext(util.Context):
    def __init__(self, m=None, parent=None, namespace=None, debug=False):
        super(ParserContext, self).__init__(m, parent)
        if namespace:
            self._namespace = namespace
        elif parent:
            self._namespace = None
        else:
            self._namespace = {}
        self._debug = debug
        self._cache = None if parent else {}

    def __repr__(self):
        return "<%s %r %r>" % (type(self).__name__,
                               list(self.namespace.keys()),
                               list(self.keys()))

    @property
    def namespace(self):
        return self.parent.namespace if self.parent else self._namespace

    @property
    def debug(self):
        return self._debug or (self.parent and self.parent.debug)

    @property
    def cache(self):
        return self.parent.cache if self.parent else self._cache

    def set_debug(self, v):
        self._debug = v
        return self


def condition_string(c, add_eot=True):
    # Remove stray BOM
    if c and c[0] == u"\ufeff":
        c = c[1:]

    c = c.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " " * 8)

    if add_eot and not c.endswith("\x03"):
        c += u"\x03"
    return c



