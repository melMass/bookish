jQuery.fn.searchbox = function(delay) {
    return this.each(function() {
        if (delay === undefined) {
            delay = 250;
        }

        // Grab a jQuery reference to the textbox
        var textbox = $(this);
        var boxid = textbox.attr("id");

        // Look for options in data- attributes on the search box
        var searchpath = textbox.attr("data-path") || "/_search";
        var noPopup = textbox.attr("data-popup") == "false";
        var require = textbox.attr("data-require");
        var lang = textbox.attr("data-lang") || "en";

        // Create a div for the search results and append it to the body
        var resultsdiv = $('<div id="' + boxid + '-results">').attr("class", "search-results");

        var catname = null;
        var resultcount = 0;
        var selected = 0;
        var sequence = -1;
        var lastqstring = null;
        var timer = null;
        var body = $("body");

        if (!noPopup) {
            body.mouseup(function (e) {
                if (e.target !== textbox[0]
                    && $(e.target).closest(resultsdiv).length == 0) {
                    hideResults()
                }
            })
        }

        var resultsparent = noPopup ? textbox.parent() : body;
        resultsparent.append(resultsdiv);

        textbox.focus(function() {
           update();
        }).blur(function() {
            //setTimeout(hideResults, 500);
        }).keydown(function(e) {
            var keycode = e.keyCode || window.event.keyCode;
			var rc = true;

			if (keycode == 13) {
				// Enter
				enterClick();
				return false;
			} else if (keycode == 27) {
				// Escape
                if (!noPopup) {
                    hideResults();
                }
				return false;
			} else if (keycode == 38) {
				// Up key
				if (selected == 0 || selected == -1) {
					selected = resultcount - 1;
				} else {
					selected--;
				}
				updateCss();
				rc = false;
			} else if (keycode == 40) {
				// Down key
				if (selected == resultcount - 1) {
					selected = 0;
				} else {
					selected++;
				}
				updateCss();
				rc = false;
			} else {
				if (timer) {
					clearTimeout(timer);
				}
				selected = 0;
			}

			timer = setTimeout(update, delay);
			return rc;
        });

        function updateCss() {
			resultsdiv.find(".hit").each(function(i) {
				if (i == selected) {
					$(this).addClass("selected");
				} else {
					$(this).removeClass("selected");
				}
			});
		}

        function setCategory(name) {
            catname = name;
            update(true);
        }

        function enterClick(e) {
            if (e) {
                // User might have clicked an element inside the list item, so
                // find the closest list item
                e = $(e).closest(".hit")
            } else {
                e = resultsdiv.find(".hit.selected")
            }

            if (e.hasClass("more")) {
                setCategory(e.parent().attr("data-name"));
            } else if (e.hasClass("findpage")) {
                window.location = "/find?q=" + encodeURIComponent(textbox.val());
            } else {
                var href = e.find("a").attr("href");
                if (href) {
                    window.location = href;
                }
            }
		}

        function showResults() {
            resultsdiv.fadeIn(200);
        }
        function hideResults() {
            resultsdiv.fadeOut(200);
        }

        function fillResults(html) {
            html = $(html);
            var seq = Number(html.attr("data-sequence"));
            // console.log("Incoming seq=", seq, "current=", sequence);
            if (seq < sequence) return;

            resultsdiv.html(html);

            var hits = html.find(".hit");
            resultcount = hits.length;
            selected = 0;
            hits.mouseover(function(e) {
                var target = $(e.target);
                while (!target.hasClass("hit")) {
                    target = target.parent();
                }
                hits.each(function(i) {
                    if (this === target[0]) {
                        selected = i;
                        $(this).addClass("selected");
                    } else {
                        $(this).removeClass("selected");
                    }
                });
            }).click(function(e) {
                enterClick(e.target);
            });
            
            var cats = html.find(".cat");
            cats.click(function(e) {
                setCategory($(this).attr("data-name"));
            });

            updateCss();
        }

        function update(force) {
            var qstring = textbox.val();
            if (qstring === "") {
                catname = null;
            }
            showResults();
            if (force || qstring !== lastqstring) {
                //var startpos = getSelectionStart(box);
                //var endpos = getSelectionEnd(box);

                sequence++;
                //console.log("Running", qstring, catname, sequence);
                $.ajax(searchpath, {
                    data: {
                        q: qstring,
                        sequence: sequence,
                        category: catname,
                        require: require,
                        permanent: noPopup ? "true" : "false",
                        lang: lang
                        //startpos: startpos,
                        //endpos: endpos,
                    },
                    success: function (data) {
                        fillResults(data);
                    },
                    error: function (data) {
                        console.log("Search error");
                    }
                });
                lastqstring = qstring;
            }
        }

        if (noPopup) {
            update();
        }
    });
};

