window.sidebarClosed = true;
window.sidebarWidth = 320;

// A 1x1 transparent pixel PNG image, encoded as a data: URI
var pixel_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP6zwAAAgcBApocMXEAAAAASUVORK5CYII="


function isEmbeddedBrowser() {
    if (window.Python) {
        return true;
    }

    // In Qt5, the window.Python object may not be initialized yet
    // so we also check for the existence of the qt.webChannelTransport
    if (window.qt && window.qt.webChannelTransport) {
        return true;
    }

    return false;
}

function getSelectionStart(o) {
    if (o.createTextRange) {
        var r = document.selection.createRange().duplicate();
        r.moveEnd('character', o.value.length);
        if (r.text == '') return o.value.length;
        return o.value.lastIndexOf(r.text);
    } else return o.selectionStart;
}

function getSelectionEnd(o) {
    if (o.createTextRange) {
        var r = document.selection.createRange().duplicate();
        r.moveStart('character', -o.value.length);
        return r.text.length;
    } else return o.selectionEnd;
}

function getVimeoThumbnail(vid, size, callback) {
    $.getJSON('http://www.vimeo.com/api/v2/video/' + vid + '.json?callback=?', {
            format: "json"
        },
        function(data) {
            callback(data[0]["thumbnail_" + size]);
        }
    );
}

function setUpImageComparisons() {
    $(".image-comparison").each(function() {
        var elem = $(this);
        var pressed = false;
        var img1 = elem.find(".img1");
        var img2 = elem.find(".img2");
        var slider = $("<div class='compare-slider'></div>");
        $(img1).before(slider);

        // TODO: need to reposition everything on resize
        slider.mousedown(startSlide);
        slide(img1.width() / 2);

        function startSlide(e) {
            e.preventDefault();
            pressed = true;
            $(window).mousemove(moveSlide);
            $(window).mouseup(endSlide);
        }

        function endSlide(e) {
            pressed = false;
            return false;
        }

        function moveSlide(e) {
            if (!pressed) {
                return false
            }
            if (!(e.buttons & 1)) {
                return endSlide(e)
            }
            var pos = getCursorPos(e);
            var w = img2.width();
            if (pos < 0) pos = 0;
            if (pos > w) pos = w;
            slide(pos);
        }

        function getCursorPos(e) {
            e = e || window.event;
            var a = img1[0].getBoundingClientRect();
            var x = e.pageX - a.left;
            return x - window.pageXOffset;
        }

        function slide(x) {
            img2.css("clip", "rect(0px, " + x + "px, auto, auto)");

            var left = (x - slider.width() / 2) + "px";
            slider.css("left", left);
        }
    });
}


function updateHash() {
    // If the hash element exists and is collapsible, de-collapse it
    var id = window.location.hash;
    var e = $(id);
    if (e.length > 0 && e.hasClass("collapsible")) {
        e.removeClass("collapsed");
    }

    setTimeout(window.scrollBy(0, -32), 20);
}

function zoomImage(e) {
    e.preventDefault();
    var el = $(this);
    var src = el.find("img").attr("src");
    var lbox = $("#lightbox");
    if (lbox.length == 0) {
        lbox = $("<div id='lightbox'><img src='" + src + "'/></div>");
        $("body").append(lbox);
        lbox.click(function(e) {
            lbox.hide();
        });
    } else {
        lbox.find("img").attr("src", src);
    }

    lbox.show();
    lbox.offset({
        left: 0,
        top: el.offset().top
    });
}


function setUpCharts(spec) {
    spec = spec || "#content";
    $(spec + " .chart").each(function() {
        var e = $(this);
        try {
            var data = JSON.parse(e.attr("data-data"));

            var opts = {
                shadowSize: 0
            };
            var options = JSON.parse(e.attr("data-options"));
            for (var k in options) {
                opts[k] = options[k];
            }

            options.shadowSize = 0;
            e.plot(data, opts).data("plot");
        } catch (e) {
            //
        }
    })
}

function setUpTabs() {
    $(".tab-group").each(function() {
        var e = $(this);
        var tabs = e.find(".tab-heading > .label");
        var bodies = e.find(".tab-bodies > .content");

        tabs.click(function() {
            var e = $(this);
            tabs.each(function() {
                $(this).removeClass("selected");
            });
            bodies.each(function() {
                $(this).removeClass("selected");
            });
            e.addClass("selected");
            $("#" + e.attr("for")).addClass("selected");
        })
    })
}


function setUpVimeoBackwardsCompatibility() {
    // Remove this when the embedded browser can show video

    if (isEmbeddedBrowser()) {
        // We are running in the embedded help browser which currently does
        // not have video support. Replace vimeo iframes with a clickable links.
        $(".vimeo.video").each(function() {
            // Grab the iframe
            var frame = $(this);
            // Get the attrs from the frame
            // var src = frame.attr("src");
            var vidid = frame.attr("data-vimeo-id");
            var desc = frame.attr("title");
            var src = "https://vimeo.com/" + vidid;
            // Make a link element for the video
            var link = $("<a href='" + src + "'>" + desc + " video</a>");
            // Attach a click handler to open the URL in a real browser
            link.click(function() {
                return openURLInExternalBrowser(src);
            });
            // Make a div element that will have the video thumbnail as a
            // background image
            var linkdiv = $("<div class='replaced-vimeo'>");
            // Put the link inside the div
            linkdiv.append(link);
            // Replace the iframe with the div
            $(this).replaceWith(linkdiv);
            // Run the async request to get the video thumbnail
            getVimeoThumbnail(vidid, "small", function(imgurl) {
                linkdiv.css("background-image", "url('" + imgurl + "')");
            });
        })
    }
}


function setUpThumbnails() {
    $(".vimeo-reference").each(function() {
        var e = $(this);
        var vid = e.attr("data-vid");
        getVimeoThumbnail(vid, "small", function(imgurl) {
            e.find(".thumbnail").append(
                $("<img src='" + imgurl + "'>")
            )
        })
    })
}


function setUpSearch() {
    $(".search").searchbox();
    $(".search-button").click(function() {
        $(this).parent().find(".search").focus()
    });

    $(".livesearch .search").first().focus();
}


function setUpIconErrors() {
    $("img.icon").on("error", function() {
        $(this).attr("data-old-src", $(this).attr("src"));
        $(this).unbind("error").attr("src", pixel_uri);
    });
}


function scrollToc() {
    // Scroll the TOC to show the entry for the current page if it's not visible
    var toc = $("#toc");
    var here = toc.find(".here");
    if (here.length > 0) {
        // Get the offset of the "here" div
        var y = here.offset().top;
        var height = toc.height();
        if (y > (height - 32)) {
            // If the "here" div is "offscreen" (more or less), scroll to it

            // Don't just scroll right to it so it's the first item; it's nicer
            // to place it 1/3 of the way from the top
            y -= height * 0.33;
            if (y < 0) {
                y = 0;
            }

            toc.scrollTop(y);
        }
    }
}

function initHoudiniWebChannel() {
    if (!window.qt || !window.qt.webChannelTransport) {
        // The web channel transport is not available so we must not
        // be running in the QWebEngine embedded browser
        return;
    }

    new QWebChannel(qt.webChannelTransport, function(channel) {
        window.Python = channel.objects.Python;
    });
}

function setUpPage() {
    var istop = window.self === window.top;

    initHoudiniWebChannel();

    if (istop) {
        setUpSearch();

        $(window).on("hashchange", updateHash);
        if (location.hash) {
            setTimeout(updateHash, 50);
        }
    }

    // Set up the "on this page" select menu
    $("#onthispage").change(function() {
        location.hash = $(this).val()
    });

    $("img.animated").each(function() {
        var img = $(this);
        img.click(function() {
            var anim = img.attr("data-anim");
            var stat = img.attr("data-static");

            if (img.hasClass("running")) {
                img.removeClass("running");
                img.attr("src", stat);
            } else {
                img.addClass("running");
                img.attr("src", anim);
            }
        })
    });
    $(".billboard.animated").each(function() {
        var bb = $(this);
        bb.click(function() {
            var src = bb.css("background-image");
            var anim = "url('" + bb.attr("data-anim") + "')";
            var stat = "url('" + bb.attr("data-static") + "')";

            if (bb.hasClass("running")) {
                bb.removeClass("running");
                bb.css("background-image", stat);
            } else {
                bb.addClass("running");
                bb.css("background-image", anim);
            }
        })
    });

    // Add a general click handler for labels inside collapsible elements
    $(document).on("click", ".collapsible > .label", function() {
        var label = $(this);
        var parent = label.parent();
        if (parent.hasClass("collapsed")) {
            parent.removeClass("collapsed");
        } else {
            parent.addClass("collapsed");
        }
    });

    $(".load-example").each(function() {
        var btn = $(this);
        btn.click(function(e) {
            var path = btn.attr("data-path");
            var launch = btn.attr("data-launch") == "True";
            loadExample(path, launch);
        })
    });

    scrollToc();
    setUpCharts();
    setUpTabs();
    setUpThumbnails();
    setUpIconErrors();
    // Remove this when the embedded browser can show video
    setUpVimeoBackwardsCompatibility();
    $("figure.unzoomed").click(zoomImage).attr("title", "Click to zoom")
}

function openURLInExternalBrowser(url) {
    if (!window.Python) {
        return true;
    }

    var py_statements = "__import__('webbrowser').open_new_tab('" + url + "')";
    window.Python.runStatements(py_statements);
    return false;
}

$(document).ready(setUpPage);
$(window).on("load", setUpImageComparisons)
