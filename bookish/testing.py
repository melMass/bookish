# Copyright 2017 Matt Chaput. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
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

from bookish import functions, paths, util


def find_missing(pages, images=True, links=True, prefix="/", callback=None):
    all_images = set()
    used_images = set()
    missing = []
    # Look at every file in the virtual filesystem...
    for path in util.get_prefixed_paths(pages, prefix):
        # If this is an image, remember it for later
        if paths.extension(path) in (".png", ".jpg", ".jpeg", ".gif"):
            all_images.add(path)

        # If this not a wiki page, ignore it
        if not pages.is_wiki_source(path):
            continue

        # Parse the wiki page and look for links inside
        if callback:
            callback(path)
        json = pages.json(path)
        for link in functions.find_links(json):
            value = link["value"]
            scheme = link.get("scheme")

            # Ignore icon links
            if value.startswith("#") or scheme in ("Icon", "Smallicon", "Largeicon"):
                continue

            linkpath = link.get("fullpath")
            if not linkpath:
                continue

            # If this is a link to a wiki page, convert the path to the source
            # (.txt) path
            if pages.is_wiki(linkpath):
                linkpath = pages.source_path(linkpath)
            # Check if the path exists in the VFS
            exists = pages.exists(linkpath)

            # If the link is to an image, remember that there was a reference
            # to this image (in used_images)
            isimage = scheme in ("Image", "Anim")
            if isimage:
                used_images.add(linkpath)
                if scheme == "Anim":
                    poster = paths.basepath(linkpath) + "_poster.gif"
                    used_images.add(poster)

            # If the referenced resource exists, there's no problem, escape
            # early
            if exists:
                continue

            if (images and isimage) or (links and not isimage):
                missing.append((path, value, linkpath))

    # Find images that exist but aren't used in the docs
    unused_images = all_images - used_images

    # Return a tuple of a list of broken links, and a set of unused images
    return missing, unused_images

