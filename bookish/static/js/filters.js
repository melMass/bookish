// A function that returns a comparator for the given attribute on elements
function cmpAttribute(name) {
    return function(a, b) {
        var aa = a.getAttribute(name);
        var bb = b.getAttribute(name);
        return aa.localeCompare(bb);
    }
}

// Updates the visibility of collapsible elements
function updateCollapses(e, collapse) {
    var collapsibles = $(e).find(".collapsible");
    collapsibles.each(function() {
        if (collapse) {
            $(this).addClass("collapsed");
        } else {
            $(this).removeClass("collapsed");
        }
    })
}

// Updates the visibility of items inside a filtered element
function updateFilter(event, e, clear) {
    var controls = e.children(".interface");
    var orig = e.children(".original");
    var title = controls.find(".title-filter");
    // Set the original items as the default source for filtering
    var source = orig;

    // Choose which set of items to update, based on the sort menu.
    // This is inside an each because the menu might not exist.
    controls.find(".sort").each(function() {
        var sortedby = $(this).val();
        if (sortedby === "source") {
            // Hide the sorted clones
            e.children(".sorted").hide();
            // Use the original items for filtering
            source = orig;
        } else if (sortedby === "alpha") {
            // Hide the original items
            orig.hide();
            // Get the sorted clones for filtering
            source = e.children(".sorted");
            // If the sorted clones don't exist yet, create them
            if (source.length == 0) {
                // Create an element to hold the clones
                source = $('<' + orig[0].tagName + ' class="sorted filtered-body">');
                // Find the original items and sort them by the title attribute
                var items = orig.find(".item");
                items.sort(cmpAttribute("data-title"));
                // Clone the original elements into the holder element
                items.each(function() {
                    $(this).clone(true, true).appendTo(source);
                });
                // Append the holder element to the filtered element
                e.append(source);
            }
        }
    });

    // Show everything
    source.show();
    source.find("section.heading").show();
    source.find(".item").show();

    // Build a CSS selector...
    var selector = "";

    // Tags
    controls.find(".tags").each(function() {
        var select = $(this);
        var tag = select.val();
        if (tag !== "*") {
            if (clear) title.val("");
            selector += "[data-tags~=\"" + tag + "\"]";
        }
    });

    // Custom menus in the filter ui
    controls.find(".filter-menu").each(function() {
        // Grab the select element
        var select = $(this);
        // Get the search field name associated with it
        var name = select.attr("data-name");
        // Get the currently selected menu item's value
        var value = select.val();
        // The first/blank entry in the menu has the value "*" meaning no filter
        if (value != "*") {
            if (clear) title.val("");
            selector += "[data-" + name + "=\"" + value + "\"]";
        }
    });

    // Add the text search filter value to the selector
    var text = title.val().toLowerCase();
    if (text !== "") {
        selector += "[data-title*=\"" + text + "\"]";
    }

    if (selector !== "") {
        // Hide everything that doesn't match the selector
        source.find(".item:not(" + selector + ")").hide();

        // Hide headings if all items inside are hidden
        source.find("section.heading").each(function() {
            var h = $(this);
            var items = h.find(".item");
            if (!items.is(':visible')) {
                h.hide();
            } else {
                h.show();
            }
        })
    }
}

// Sets up the UI for a filtered element
function setUpFilter(e) {
    var e = $(e);
    // Get the elements inside the filtered element
    var controls = e.children(".interface");
    var orig = e.children(".original");
    var items = orig.find(".item");

    // Set up the UI on custom filter menus
    setUpCustomFilters(e, controls, items);

    // Set up the "main" (automatic) filter controls: title filter, sort menu,
    // and tags
    var mainControls = $('<span class="main"></span>');

    // Only show the title filter if any items actually have the attribute
    if (items.filter("*[data-title]").length > 0) {
        setUpTitleFilter(e, mainControls);
    }

    if (e.attr("data-sortable") == "true") {
        setUpSortMenu(e, mainControls, items);
    }
    setUpTagFilter(e, mainControls, items);
    // Put the "main" controls before the custom controls
    controls.prepend(mainControls);

    // Set up UI for collapsing/expanding all collapsible elements inside
    var collapses = orig.find(".collapsible");
    if (collapses.length >= 2) {
        // Create a "collapse all" button
        var collapseall = $('<button class="compact">Collapse All</button>');
        collapseall.click(function() { updateCollapses(e, true); });
        controls.append(collapseall);
        // Create an "expand all" button
        var expandall = $('<button class="compact">Expand All</button>');
        expandall.click(function() { updateCollapses(e, false); });
        controls.append(expandall);
    }
}

// Sets up the UI for the custom menus in a filtered element
function setUpCustomFilters(e, controls, items) {
    controls.find("select.filter-menu").each(function() {
        var select = $(this);
        var name = select.attr("data-name");
        var counts = {};
        items.each(function() {
            var val = $(this).attr("data-" + name);
            if (val && val !== "") {
                if (counts.hasOwnProperty(val)) {
                    counts[val] += 1;
                } else {
                    counts[val] = 1;
                }
            }
        });

        var allVals = Object.keys(counts);
        allVals.sort();
        var val;
        for (var i = 0; i < allVals.length; i++) {
            val = allVals[i];
            select.append($('<option>', {
                value: val, text: val + " (" + counts[val] + ")"
            }))
        }

        select.change(function(event) {updateFilter(event, e, true)});
    });
}

// Sets up the UI for the title filter text box in a filtered element
function setUpTitleFilter(e, controls) {
    var textbox = $("<input class='title-filter' placeholder='Filter'>");
    textbox.keyup(function(event) {updateFilter(event, e)});
    controls.append(textbox);
}

// Sets up the UI for the "sort"
function setUpSortMenu(e, controls, items) {
    if (items.length <= 2) {
        return;
    }

    var select = $('<select class="sort"><option value="source">Original order</option></select>');
    select.append($('<option value="alpha">Sorted by title</option>'));

    for (var i = 0; i < items.length; i++) {
        if (items[i].hasAttribute("data-group")) {
            select.append($('<option value="groups">Sort by groups</option>'));
            break;
        }
    }
    select.change(function(event) {updateFilter(event, e)});
    controls.append(select);
}

// Sets up the UI for tagged items inside a filtered element
function setUpTagFilter(e, controls, items) {
    var hasTags = false;
    var tagCounts = {};

    items.filter(function() {return this.hasAttribute("data-tags")}).each(function() {
        var tagString = this.getAttribute("data-tags");
        if (tagString && tagString !== "") {
            hasTags = true;
            var tagList = tagString.split(" ");
            var tag;
            for (var i = 0; i < tagList.length; i++) {
                tag = tagList[i];
                if (tagCounts.hasOwnProperty(tag)) {
                    tagCounts[tag] += 1;
                } else {
                    tagCounts[tag] = 1;
                }
            }
        }
    });

    if (hasTags) {
        var allTags = Object.keys(tagCounts);
        allTags.sort();
        var select = $('<select class="tags"><option value="*">All tags</option></select>');
        var tag;
        for (var i = 0; i < allTags.length; i++) {
            tag = allTags[i];
            select.append($('<option>', {
                value: tag, text: tag + " (" + tagCounts[tag] + ")"
            }))
        }
        select.change(function(event) {updateFilter(event, e, true)});
        controls.append(select);
    }
}

$(document).ready(function() {
    // Find any filtered elements and set up their UI
    $(".filtered").each(function() {
        setUpFilter(this);
    });
});
