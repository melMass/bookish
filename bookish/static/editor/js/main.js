// Use JSON data to display the directory hierarchy
// Input JSON has to be an array of objects
function displayDirectory(data, output, indent, callback) {
    if (Array.isArray(data)) {
        data.sort(function (a, b) {
            if (a.isdir && !b.isdir) {
                return -1;
            }
            if (b.isdir && !a.isdir) {
                return 1;
            }
            return (a.name < b.name) ? -1 : (a.name > b.name) ? 1 : 0;
        });
        for (var i = 0; i < data.length; i++) {
            var li = $("<li>").attr({
                "indent": indent
            });
            var link = $("<a href=\"#\">").html(data[i].name).attr("path", data[i].path);
            if (data[i].isdir) {
                link.addClass("isDir");
                li.attr("id", "dir_" + data[i].path.substring(1).split(".").join("_").split("/").join("_"));
                link.prepend("<span class=\"glyphicon glyphicon-menu-right\"aria-hidden=\"true\">");
            }
            else {
                link.addClass("isFile");
                li.attr("id", "file_" + data[i].path.substring(1).split(".").join("_").split("/").join("_"));
                link.prepend("<span class=\"glyphicon glyphicon-file\"aria-hidden=\"true\">");
            }
            link.appendTo(li);
            li.appendTo(output);
        }
        if (callback) {
            callback();
        }
    }
}

// Use JSON data to display subdirectories
// Add collapse panel so that the directory tree can be folded
// Eventually call displayDirectory to insert list items for each directory
function displaySubDirectory(data, output, callback) {
    output.attr("role", "tab").addClass("subDirLoaded");
    output.children("a").attr({
        "data-toggle": "collapse",
        "href": "#subDir_" + output.text(),
        "aria-expanded": "true",
        "aria-controls": "subDir_" + output.text()
    });
    var div = $("<div>").addClass("panel-collapse collapse in").attr({
        "id": "subDir_" + output.text(),
        "role": "tabpanel",
        "aria-labelledby": output.attr("id")
    });
    displayDirectory(data.files, div, parseInt(output.attr("indent")) + 1, callback);
    output.after(div);
}

// Add the filename to recently visited list
function addToRecentlyVisited(path, list) {
    if (list.length > 10) {
        list.splice(0, 1);
        $("#recentlyVisited ul").children("li[index='" + list.length + "']").remove();
    }
    var oldIndex = list.indexOf(path);
    if (oldIndex < 0) { // Not in recently visited list before
        var newLi = $("<li>")
            .append($("<a href=\"#\">").addClass("visitedFile").text(path.substring(1))
                .prepend($("<span class=\"glyphicon glyphicon-file\" aria-hidden=\"true\">")));
        $("#recentlyVisited ul").prepend(newLi);
    }
    else {
        list.splice(oldIndex, 1);
        $("#recentlyVisited ul").children("li:eq(" + oldIndex + ")").prependTo($("#recentlyVisited ul")); // Move to Front
    }
    list.unshift(path);
}

// Hide the tabs in dropdown list when the total length of all tabs exceeds the limit
// Make sure at least one tab is shown
function hideTab(totalLength, maximumLength, totalTabs, tabSize) {
    if (totalTabs === 1) {
        return;
    }
    var fromIndex = -1;
    var toIndex = 0;
    while (totalLength >= maximumLength) {
        var firstTab = $(".titleBar .nav li[index='" + toIndex + "']");
        if (firstTab.length && !firstTab.hasClass("hiddenTab")) {
            if (fromIndex === -1) {
                fromIndex = toIndex;
            }
            totalLength -= firstTab.outerWidth();
            tabSize.push(firstTab.outerWidth());
        }
        toIndex++;
        if (toIndex === totalTabs) {
            toIndex--;
            break;
        }
    }
    if (fromIndex >= 0) { // At least one tab needs to be hidden
        var hiddenTabs = $(".hiddenTabs .hiddenList");
        if (fromIndex === 0) {
            hiddenTabs.prepend($("<li>").attr("role", "separator").addClass("divider"));
        }
        for (var i = fromIndex; i < toIndex; i++) {
            var tobeRemoved = $(".titleBar .nav li[index='" + i + "']");
            var path = tobeRemoved.children("a").text();
            var link = $("<a>")
                .attr({
                    "href": "#",
                    "path": path,
                    "title": path
                });
            if (path.length > 22) {
                link.text("..." + path.substring(path.length - 19, path.length)); // Only show the latter part of file name if it's too long
            }
            else {
                link.text(path);
            }

            hiddenTabs
                .prepend($("<li>")
                    .attr("index", i)
                    .append(link));
            tobeRemoved.remove();
        }
    }
    return totalLength;
}

// Re-insert the tab into titlebar when spaces available
function showTab() {
    var tobeShown = $(".hiddenTabs li").first();
    var link = tobeShown.children("a");
    var newTab = $("<li>")
        .attr("index", tobeShown.attr("index"));
    link.text(link.attr("path"));
    link.appendTo(newTab);
    newTab.append($("<span class=\"glyphicon glyphicon-remove closeTab\">"));
    if (tobeShown.hasClass("activeTab")) {
        newTab.addClass("activeTab");
    }
    tobeShown.remove();
    if ($(".hiddenTabs li").length === 2) { // remove separator when there is no hidden tabs
        $(".hiddenTabs li[role='separator']").remove();
    }
    newTab.prependTo($(".titleBar .nav"));
}

// AJAX call to get directory data from backend
function loadDirectory(url, path, callback) {
    $.ajax(url, {
        type: "GET",
        data: {
            path: path
        },
        success: function (data, status) {
            callback(null, data);
        },
        error: function (data, status) {
            alert("Loading failed!");
            callback(status);
        }
    });
}

// AJAX call to get file content from backend
function loadFile(url, callback) {
    $.ajax(url, {
        type: "GET",
        cache: false,
        "Content-Type": "text/plain",
        success: function (data, status) {
            callback(null, data);
        },
        error: function (data, status) {
            alert("Accessing file failed!");
            callback(status);
        }
    });
}

// AJAX call to save changed content
function saveChange(content, url, callback) {
    $("#preview").addClass("saving");
    $.ajax("/_save/", {
        type: "PUT",
        data: {
            path: url,
            source: content
        },
        success: function (data, status) {
            callback(true);
        },
        error: function (data, status) {
            alert("Saving failed!\n" + data.responseText);
            callback(false);
        },
        complete: function (data, status) {
            $("#preview").removeClass("saving");
        }
    });
}

// AJAX call to delete file
function deleteFile(path, id) {
    $.ajax("/_delete/", {
        type: "PUT",
        data: {
            path: path
        },
        success: function (data, status) {
            if (id) {
                $(".directoryList li#" + id + "").remove();
            }
        },
        error: function (data, status) {
            alert("Deleting failed!\n" + data.responseText);
        }
    });
}

// AJAX call to rename file
function renameFile(oldPath, newPath, content, callback) {
    $.ajax("/_move/", {
        type: "PUT",
        data: {
            path: oldPath,
            newpath: newPath
        },
        success: function (data, status) {
            var input = $("#replaceFileNameInput");
            var aLink = input.next("a");
            input.parent().attr("id", "file_" + newPath.substring(1).split(".").join("_").split("/").join("_"));
            var icon = aLink.children("span");
            aLink.attr("path", newPath).css("display", "block").text(newPath.substring(newPath.lastIndexOf("/") + 1));
            icon.prependTo(aLink);
            input.blur();
            callback(true);
        },
        error: function (data, status) {
            alert("Renaming failed!\n" + data.responseText);
        }
    });
}

// AJAX call to create a new directory
function mkdir(path, callback) {
    $.ajax("/_make_dir/", {
        type: "PUT",
        data: {
            path: path
        }, success: function (data, status) {
            callback(true);
        }, error: function (data, status) {
            alert("Making new directory failed!");
            callback(false);
        }
    });
}

// Create an input block for user to input the name for new file/directory
function createNewItem(type) {
    var currentDirectory = $(".directorySelected");
    // new input box
    var newLi = $("<li>").addClass("new" + type + "Entry").append($("<input>").attr({
        type: "text",
        id: "new" + type + "NameInput"
    }));
    var aLink = currentDirectory.children("a");
    if (currentDirectory.next().length) {
        var nextDiv = currentDirectory.next();
        newLi.attr({
            indent: parseInt(currentDirectory.attr("indent")) + 1
        });
        if (nextDiv.is("div") && currentDirectory.hasClass("subDirLoaded")) { // directory has been opened before
            if (aLink.hasClass("collapsed")) {
                $.when(loadDirHelper(aLink)).then(function () {
                    newLi.appendTo(nextDiv);
                    newLi.children("input").focus();
                });
            }
            else {
                newLi.appendTo(nextDiv);
                newLi.children("input").focus();
            }
        }
        else {
            var path = aLink.attr("path");
            aLink.children("span").removeClass("glyphicon-menu-right").addClass("glyphicon-menu-down");
            loadDirectory("/_dir", path, function (err, data) {
                if (err) {
                    return alert(err);
                }
                displaySubDirectory(data, currentDirectory, function () {
                    $("div#" + aLink.attr("href").substring(1)).ready(function () { // keep it running in synchronize way
                        newLi.appendTo($("div#" + aLink.attr("href").substring(1)));
                        newLi.children("input").focus();
                    });
                });
            });
        }
    }
    else { // at root
        newLi.appendTo(currentDirectory);
        newLi.attr({ indent: 0 });
    }
    var indentPx = parseInt(newLi.attr("indent")) * 20 + 12;
    newLi.children("input").css("width", (currentDirectory.outerWidth() - indentPx) + "px");
    newLi.children("input").css("marginLeft", indentPx + "px");
    newLi.children("input").focus();
}

// Select the item on which right click happens
function rightClickSelect(callback) {
    $(".sideBarRightClick").removeClass("open");
    var target = $(".sideBarRightClick").attr("target");
    var targetLink = $(".directoryList a[path='" + target + "']");
    $(".directorySelected").removeClass("directorySelected");
    if (targetLink.hasClass("isDir")) {
        targetLink.parent().addClass("directorySelected");
    }
    else if (targetLink.parent().parent().prev().length) {
        targetLink.parent().parent().prev().addClass("directorySelected");
    }
    else { // root directory
        targetLink.parent().parent().addClass("directorySelected");
    }
    callback();
}

$(document).ready(function () {

    /******************************************************
     ******************* Initialization *******************
     ******************************************************/
    var DirectoryUrl = "/_dir";
    var dragging;
    var contentModified = false;
    var filePanelHidden = false;
    var previewPanelHidden = false;
    var lineNumHidden = false;
    var colorTheme = "default";
    var activeFile = [];
    var modifiedFile = [];
    var visitedList = [];
    var hiddenTabSize = [];
    var cmInstanceList = [];
    var activeTabPos = -1;
    var tabTotalLength = $(".hiddenTabs").outerWidth();
    var titleBarLengthMaximum = $(".titleBar").outerWidth() - 20;

    var previewer = {
        previewing: false,
        needsPreview: false,
        previewTimer: null,
        preview: function (cm) { // calling back-end to get the preview for current file content
            var that = this;
            if (that.previewing) {
                that.needsPreview = true;
                return;
            } else {
                that.previewing = true;
                that.needsPreview = false;
            }
            if (cm.getValue() === "") {
                frames[0].document.write();
                that.previewing = false;
                that.needsPreview = false;
                return;
            }
            $.ajax("/_preview/", {
                type: "PUT",
                data: {
                    path: $(".activeTab").children("a").text(),
                    source: cm.getValue(),
                    scrollTop: $("#preview").contents().scrollTop(),
                    autosave: true
                },
                success: function (data, status) {
                    var frame = window.frames[0];
                    var doc = frame.document;
                    doc.open();
                    doc.write(data.html);
                    doc.close();

                    $(frame).scrollTop(data.scrollTop);
                    that.previewing = false;
                    if (that.needsPreview) {
                        that.needsPreview = false;
                        that.preview(cm);
                    }
                },
                complete: function (data, status) {
                    that.previewing = false;
                }
            });
        }
    };
    var history = {
        _history_url: "/_list_checkpoints/",
        _load_url: "/_load_checkpoint/",
        _modalBody: $("#HistorySelectDialog tbody"),
        currentPath: "",
        historyList: {},
        getHistory: function (path) { // read all the checkpoints for the file on the path, if path is not specified, read the checkpoints for current active file
            var that = this;
            if (!path) {
                path = that.currentPath;
            }
            $.ajax(that._history_url, {
                type: "GET",
                data: {
                    path: path
                },
                success: function (data, status) {
                    that.historyList[path] = data.checkpoints;
                },
                error: function (data, status) {
                    alert("Loading failed!");
                    // callback(status);
                }
            });
        },
        display: function () { // show checkpoints list in the pop up model
            var that = this;
            that._modalBody.empty();
            var his_list = that.historyList[that.currentPath];
            if (!his_list) {
                if (that.currentPath === "") {
                    alert("Please select a file first.");
                }
                else {
                    alert("No history record found!");
                }
                return false;
            }
            for (var i = his_list.length - 1; i > -1; i--) {
                var tr = $("<tr>").append($("<td>").text(his_list[i].modified)).append($("<td>").text(his_list[i].id));
                var radio = $("<td>").append($("<input type='radio' name='historyRadio' class='historyRadio' id='historyRadio_" + i + "' value=" + his_list[i].id + ">"));
                radio.prependTo(tr);
                tr.appendTo(that._modalBody);
            }
            return true;
        },
        loadContent: function (id, callback) { // load content from certain checkpoint
            var that = this;
            $.ajax(that._load_url, {
                type: "GET",
                data: {
                    path: that.currentPath,
                    id: id
                },
                success: function (data, status) {
                    callback(null, data);
                },
                error: function (data, status) {
                    alert("Loading failed!");
                    callback(status);
                }
            });
        }
    };

    // Initialize codeMirror
    var codeMirror = CodeMirror(document.getElementById("editorWrap"), {
        mode: "bookish",
        lineWrapping: true,
        tabSize: 4,
        indentUnit: 4,
        undoDepth: 1000,
        lineNumbers: true
    });
    cmInstanceList.push(codeMirror);
    $(".editorWrap .CodeMirror:eq(0)").addClass("open");
    var charWidth = codeMirror.defaultCharWidth();
    var basePadding = 4;
    codeMirror.on("renderLine", function (cm, line, elt) {
        var off = CodeMirror.countColumn(line.text, null, cm.getOption("tabSize")) * charWidth;
        elt.style.textIndent = "-" + off + "px";
        elt.style.paddingLeft = (basePadding + off) + "px";
    });

    // Handle cookies
    if (!$.isEmptyObject(Cookies.get("editorCookie"))) {
        var cookie = Cookies.getJSON("editorCookie");
        $("link[title='colorTheme']").attr("href", "css/color-" + cookie.colorTheme + ".css");
        if (cookie.colorTheme === "light") {
            codeMirror.setOption("theme", "default");
            colorTheme = "default";
        }
        else {
            codeMirror.setOption("theme", "monokai");
            colorTheme = "monokai";
        }
    }

    // Adjust the submenu position relative to parent elements
    $(".containsSubMenu").each(function () {
        var index = $(this).index();
        if (index === 0) {
            $(this).children(".dropdown-submenu").css("top", "-1px");
        }
        else {
            $(this).children(".dropdown-submenu").css("top", (5 + index * 26) + "px");
        }
    });

    // Initialize side bar with root directory
    loadDirectory(DirectoryUrl, "/", function (err, data) {
        if (err) {
            return alert(err);
        }
        var ul = $("ul.directoryList");
        displayDirectory(data.files, ul, 0);
    });

    /*********************************************************
     ******************** Helper function ********************
     *********************************************************/

    // Helper function to load directory content
    var loadDirHelper = function (target) {
        var _this;
        if (target instanceof jQuery) {
            _this = target;
        }
        else {
            _this = $(target);
        }
        if (_this.is("span")) {
            _this = _this.parent();
        }
        var path = _this.attr("path");
        var parent = _this.parent();
        $(".directorySelected").removeClass("directorySelected");
        if (!parent.hasClass("subDirLoaded")) {// directory never been opened before
            _this.children("span").removeClass("glyphicon-menu-right").addClass("glyphicon-menu-down");
            loadDirectory(DirectoryUrl, path, function (err, data) {
                if (err) {
                    return alert(err);
                }
                displaySubDirectory(data, parent);
                parent.addClass("directorySelected");
            });
        }
        else {
            if (_this.attr("aria-expanded") === "true") {
                parent.addClass("directorySelected");
                _this.children("span").removeClass("glyphicon-menu-right").addClass("glyphicon-menu-down");
            }
            else {
                if (parent.parent().prev().length) {
                    parent.parent().prev().addClass("directorySelected");
                }
                else {
                    parent.parent().addClass("directorySelected");
                }
                _this.children("span").addClass("glyphicon-menu-right").removeClass("glyphicon-menu-down");
            }
        }
    };

    // Helper function to load file
    var loadFileHelper = function (target) {
        var path;
        if (typeof target === "string") {
            path = target;
            $(".directorySelected").removeClass("directorySelected");
            $(".directoryList").addClass("directorySelected");
        }
        else {
            var _this;
            if (target instanceof jQuery) {
                _this = target;
            }
            else {
                _this = $(target);
            }
            if (_this.is("span")) {
                _this = _this.parent();
            }
            path = _this.attr("path");
            $(".fileSelected").removeClass("fileSelected");
            $(".directorySelected").removeClass("directorySelected");
            _this.parent().addClass("fileSelected");
            if (_this.parent().parent().prev().length) {
                _this.parent().parent().prev().addClass("directorySelected");
            }
            else {
                _this.parent().parent().addClass("directorySelected");
            }
        }

        var position = -1;
        for (var i = 0; i < modifiedFile.length; i++) {
            if (modifiedFile[i].path === path) {
                position = i;
                break;
            }
        }
        if (position < 0) {// never been opened before
            loadFile(path, function (err, data) {
                if (err) {
                    return alert(err);
                }
                addToRecentlyVisited(path, visitedList);
                history.currentPath = path;
                history.getHistory();
                $("li.activeTab").removeClass("activeTab");
                var newTab = $("<li>")
                    .attr("index", activeFile.length)
                    .addClass("activeTab")
                    .append($("<a href=\"#\">")
                        .text(path))
                    .append($("<span class=\"glyphicon glyphicon-remove closeTab\">"));
                newTab.appendTo($(".titleBar .nav"));
                tabTotalLength += newTab.outerWidth();
                if (tabTotalLength >= titleBarLengthMaximum) {
                    tabTotalLength = hideTab(tabTotalLength, titleBarLengthMaximum, parseInt($(".titleBar .nav li").last().attr("index")), hiddenTabSize);
                }

                activeTabPos = activeFile.length;
                if (activeTabPos !== 0) {
                    cmInstanceList.push(CodeMirror(document.getElementById("editorWrap"), {
                        mode: "bookish",
                        lineWrapping: true,
                        tabSize: 4,
                        indentUnit: 4,
                        undoDepth: 1000,
                        lineNumbers: true
                    }));
                    codeMirror = cmInstanceList[activeTabPos];
                    codeMirror.setOption("theme", colorTheme);
                    $(".editorWrap .CodeMirror.open").removeClass("open");
                    $(".editorWrap .CodeMirror:eq(" + activeTabPos + ")").addClass("open");
                }

                if (path.match(/\.png$/) || path.match(/\.jpg$/) || path.match(/\.gif$/) || path.match(/\.svg$/)) {
                    activeFile.push({
                        path: path,
                        type: "image"
                    });
                    modifiedFile.push({
                        path: path,
                        type: "image"
                    });
                    var imageNode = $("<img src='" + path + "' class='codeMirror_display_img'/>")[0];
                    codeMirror.addWidget(codeMirror.getCursor("from"), imageNode);
                    codeMirror.setOption("readOnly", "nocursor");
                    codeMirror.setOption("lineNumbers", false);
                }
                else {
                    activeFile.push({
                        path: path,
                        type: "text",
                        content: data
                    });
                    modifiedFile.push({
                        path: path,
                        type: "text",
                        content: data
                    });
                    codeMirror.getDoc().setValue(data);
                    setTimeout(function () {
                        codeMirror.refresh();
                        codeMirror.getDoc().markClean();
                    }, 1);
                }
                codeMirror.on("renderLine", function (cm, line, elt) {
                    var off = CodeMirror.countColumn(line.text, null, cm.getOption("tabSize")) * charWidth;
                    elt.style.textIndent = "-" + off + "px";
                    elt.style.paddingLeft = (basePadding + off) + "px";
                });
                if (!previewPanelHidden) {
                    previewer.preview(codeMirror);
                }
            });
        }
        else {//switch to file that has been opened
            addToRecentlyVisited(path, visitedList);
            history.currentPath = path;
            activeTabPos = position;
            $("li.activeTab").removeClass("activeTab");
            $(".titleBar li[index='" + position + "']").addClass("activeTab");
            codeMirror = cmInstanceList[position];
            $(".editorWrap .CodeMirror.open").removeClass("open");
            $(".editorWrap .CodeMirror:eq(" + position + ")").addClass("open");
            if (!previewPanelHidden) {
                previewer.preview(codeMirror);
            }
            codeMirror.getDoc().markClean();
        }
    };

    // Load new data using new root directory path
    var changeRootHelper = function (path) {
        if (path[path.length - 1] !== "/") {
            $(".sideSection_breadcrumb").attr("current-path", path + "/");
        }
        else {
            $(".sideSection_breadcrumb").attr("current-path", path);
        }
        loadDirectory(DirectoryUrl, path, function (error, data) {
            if (error) {
                return;
            }
            var ul = $("ul.directoryList");
            ul.empty();
            displayDirectory(data.files, ul, 0);
            $("#fileList").scrollTop(0);
        });
    };

    // Change the name in titleBar and recentlyVisited list when file gets renamed
    var renameHelper = function (open, oldPath, newPath) {
        if (open !== -1) {
            activeFile[open].path = newPath;
            modifiedFile[open].path = newPath;
            delete history.historyList[oldPath];
            history.getHistory(newPath);
            history.currentPath = newPath;
            $(".titleBar .nav li[index=" + open + "] a").text(newPath);
        }
        for (var i = 0; i < visitedList.length; i++) {
            if (visitedList[i] === oldPath) {
                visitedList[i] = newPath;
                var aLink = $("#recentlyVisited ul li:eq(" + i + ")").children("a");
                var span = aLink.children("span");
                aLink.text(newPath.substring(newPath.lastIndexOf('/') + 1));
                span.prependTo(aLink);
                break;
            }
        }
    };

    // Adjust items in the breadcrumb so that they don't exceed the size
    var adjustBreadcrumb = function (callback) {
        var sumOfWidth = 0;
        $(".sideSection_breadcrumb .breadcrumb > li").each(function () {
            sumOfWidth += $(this).width();
        });
        var adjusted = false;
        while (sumOfWidth >= $(".sideSection_breadcrumb").width() - 50) {
            if ($(".sideSection_breadcrumb .breadcrumb > li").length === 1) {
                break;
            }
            var firstToHide = $(".sideSection_breadcrumb .breadcrumb > li").first();
            sumOfWidth -= firstToHide.width();
            firstToHide.appendTo(".sideSection_breadcrumb .breadcrumb_hide");
            adjusted = true;
        }
        if (!adjusted) {
            do {
                var firstToShow = $(".sideSection_breadcrumb .breadcrumb > span.breadcrumb_hide > li").last();
                if (!firstToShow) {
                    break;
                }
                // the only dirty way to retrieve the width 
                firstToShow.css({ visibility: "hidden", display: "inline-block" });
                var firstWidth = firstToShow.width();
                firstToShow.css({ visibility: "", display: "" });
                if (sumOfWidth + firstWidth < $(".sideSection_breadcrumb").width() - 50) {
                    $(".sideSection_breadcrumb .breadcrumb_hide").after(firstToShow);
                    sumOfWidth += firstWidth;
                }
            }
            while (sumOfWidth < $(".sideSection_breadcrumb").width() - 50 && $(".sideSection_breadcrumb .breadcrumb > span.breadcrumb_hide > li").length > 0);
        }
        if (callback) {
            callback();
        }
    };

    // Delete tab when content has not been changed, or the change is to get discarded
    var deleteTab = function (position, parentLi) {
        //  Calculate to see if we can show hidden tabs
        tabTotalLength -= parentLi.outerWidth();
        while (hiddenTabSize.length > 0 && tabTotalLength + hiddenTabSize[hiddenTabSize.length - 1] < titleBarLengthMaximum) {
            tabTotalLength += hiddenTabSize[hiddenTabSize.length - 1];
            showTab();
            hiddenTabSize.pop();
        }
        if (position === activeTabPos) { // trying to close current active tab
            var newActiveTab;
            if (position === modifiedFile.length - 1) { // rightmost tab in the list, but 
                activeTabPos--;
                if (position !== 0) { // not the only one
                    newActiveTab = parentLi.prev();
                }
            }
            else { // tab that is not the rightmost (thus not the only one)
                activeTabPos++;
                newActiveTab = parentLi.next();
            }
            if (newActiveTab) { // more than one tab is open
                codeMirror = cmInstanceList[activeTabPos];
                var newActiveFileName = newActiveTab.children("a").text().substring(1).split(".").join("_").split("/").join("_");
                // handle class names
                $(".activeTab").removeClass("activeTab");
                newActiveTab.addClass("activeTab");
                $(".editorWrap .CodeMirror.open").removeClass("open");
                $(".editorWrap .CodeMirror:eq(" + activeTabPos + ")").addClass("open");
                $(".fileSelected").removeClass("fileSelected");
                $("li#file_" + newActiveFileName).addClass("fileSelected");
                $(".directorySelected").removeClass("directorySelected");
                if ($("li#file_" + newActiveFileName).parent().prev().length) {
                    $("li#file_" + newActiveFileName).parent().prev().addClass("directorySelected");
                }
                else {
                    $("li#file_" + newActiveFileName).parent().addClass("directorySelected");
                }
            }
        }
        if (position < activeTabPos) { // remove tab before current active tab
            activeTabPos--;
        }
        // Change index of Li 
        for (var i = position + 1; i < modifiedFile.length; i++) {
            $(".titleBar .nav li:contains('" + modifiedFile[i].path + "')").attr("index", i - 1);
        }
        // Clear data
        contentModified = false;
        activeFile.splice(position, 1);
        modifiedFile.splice(position, 1);
        delete history.historyList[parentLi.children("a").text()];
        // Remove Li and codeMirror where index === position
        parentLi.remove();
        if (cmInstanceList.length !== 1) {
            cmInstanceList.splice(position, 1);
            $(".editorWrap .CodeMirror:eq(" + position + ")").remove();
            history.currentPath = activeFile[activeTabPos].path;
            if ($(".contentModified").length > 0) { // still have tabs open that have modified content
                contentModified = true;
            }
        }
        else { // last editor
            $(".fileSelected").removeClass("fileSelected");
            $(".editorWrap .CodeMirror .codeMirror_display_img").remove();
            codeMirror.setValue("");
            codeMirror.getDoc().markClean();
            history.currentPath = "";
        }
        if (!previewPanelHidden) {
            previewer.preview(codeMirror);
        }
    };

    // Check if the content in codeMirror has been changed
    var checkForChanges = function () {
        if (activeFile.length === 0 && codeMirror.getDoc().getValue() !== "") {
            alert("You have to create a new file first.");
            codeMirror.setValue("");
            codeMirror.getDoc().markClean();
            return;
        }
        if (activeFile[activeTabPos].type === "text") {
            var currentTab = $(".titleBar li[index='" + activeTabPos + "']");
            currentTab.addClass("contentModified");
            contentModified = true;
            if (codeMirror.getValue() === activeFile[activeTabPos].content) { // content is changed back to its original value
                currentTab.removeClass("contentModified");
                if ($(".contentModified").length === 0) {
                    contentModified = false;
                }
            }
            modifiedFile[activeTabPos].content = codeMirror.getValue();
        }
    };

    /***************************************************
     ****************** Event Handler ******************
     ***************************************************/

    /***********
     * Top nav *
     ***********/

    // Switch the color theme
    $(".colorTheme_light").click(function () {
        var link = $("link[title='colorTheme']").attr("href");
        $("link[title='colorTheme']").attr("href", link.replace("dark", "light"));
        colorTheme = "default";
        for (var i = 0; i < cmInstanceList.length; i++) {
            cmInstanceList[i].setOption("theme", colorTheme);
        }
        var cookie = Cookies.getJSON("editorCookie");
        cookie.colorTheme = "light";
        Cookies.set("editorCookie", cookie, { expires: 7 });
    });
    $(".colorTheme_dark").click(function () {
        var link = $("link[title='colorTheme']").attr("href");
        $("link[title='colorTheme']").attr("href", link.replace("light", "dark"));
        colorTheme = "monokai";
        for (var i = 0; i < cmInstanceList.length; i++) {
            cmInstanceList[i].setOption("theme", colorTheme);
        }
        var cookie = Cookies.getJSON("editorCookie");
        if (!cookie) {
            cookie = {};
        }
        cookie.colorTheme = "dark";
        Cookies.set("editorCookie", cookie, { expires: 7 });
    });

    // Call createNewItem function
    $(".nav.navbar-nav .fileMenu_new_file").click(function () {
        if (filePanelHidden) {
            $(".sideSection").css("width", "");
            filePanelHidden = false;
        }
        createNewItem("File");
    });
    $(".nav.navbar-nav .fileMenu_new_dir").click(function () {
        if (filePanelHidden) {
            $(".sideSection").css("width", "");
            filePanelHidden = false;
        }
        createNewItem("Dir");
    });

    // Get data and pass to the actual save function
    $(".nav.navbar-nav .fileMenu_save").click(function () {
        var index = $(".activeTab").attr("index");
        if (undefined === index || undefined === activeFile[index]) {
            return;
        }
        if (activeFile[index].type === "text") {
            var path = activeFile[index].path;
            var currentContent = codeMirror.getValue();
            if (currentContent === activeFile[index].content) {
                return;
            }
            saveChange(currentContent, path, function (status, data) {
                if (!status) {
                    return alert(status);
                }
                // success
                $(".activeTab").removeClass("contentModified");
                contentModified = false;
                activeFile[index].content = currentContent;
                modifiedFile[index].content = currentContent;
                history.getHistory();
            });
        }
    });

    // Pop up a modal for user to select the version of content they would like to load, and write the content to codeMirror
    $(".nav.navbar-nav .fileMenu_history").click(function () {
        var success = history.display();
        if (!success) {
            return;
        }
        $("#HistorySelectDialog").modal("show");

        $("#HistorySelectDialog button.btn-success").unbind('click').click(function () {
            var totalVersion = $("#HistorySelectDialog tbody input[name=historyRadio]").length;
            var version = $("#HistorySelectDialog tbody input[name=historyRadio]:checked").val();
            if (!version && totalVersion !== 0) {
                return alert("No version selected!");
            }
            else if (totalVersion === 0) {
                return;
            }
            // Load the old file
            history.loadContent(version, function (err, data) {
                if (err) {
                    return alert(err);
                }
                codeMirror.setValue(data);
                checkForChanges();

                if (!previewPanelHidden) {
                    if (previewer.previewTimer) {
                        clearTimeout(previewer.previewTimer);
                    }
                    previewer.previewTimer = setTimeout(previewer.preview(codeMirror), 200);
                }
            });
        });
    });

    // Toggle File Panel
    $(".viewMenu_file").click(function () {
        var fileWidth;
        var editorWidth;
        if (filePanelHidden) {
            $(".sideSection").css("width", "");
            fileWidth = parseInt($(".sideSection").css("width"));
            editorWidth = parseInt($(".editorSection").css("width"));
            $(".editorSection").css("width", (editorWidth - fileWidth) + "px");
            filePanelHidden = false;
        }
        else {
            fileWidth = parseInt($(".sideSection").css("width"));
            editorWidth = parseInt($(".editorSection").css("width"));
            $(".sideSection").css("width", "0px");
            $(".editorSection").css("width", (editorWidth + fileWidth) + "px");
            filePanelHidden = true;
        }
    });

    // Toggle Preview Panel
    $(".viewMenu_preview").click(function () {
        var width;
        var editorWidth;
        if (previewPanelHidden) {
            $(".previewSection").css("width", "");
            width = parseInt($(".previewSection").css("width"));
            editorWidth = parseInt($(".editorSection").css("width"));
            $(".editorSection").css("width", (editorWidth - width) + "px");
            previewPanelHidden = false;
            if (!previewPanelHidden) {
                previewer.preview(codeMirror);
            }
        }
        else {
            width = parseInt($(".previewSection").css("width"));
            editorWidth = parseInt($(".editorSection").css("width"));
            $(".previewSection").css("width", "0px");
            $(".editorSection").css("width", (width + editorWidth) + "px");
            previewPanelHidden = true;
        }
    });

    // Toggle showing line numbers
    $(".viewMenu_lineNum").click(function () {
        for (var i = 0; i < cmInstanceList.length; i++) {
            if (!cmInstanceList[i].isReadOnly()) {
                cmInstanceList[i].setOption("lineNumbers", lineNumHidden);
            }
        }
        lineNumHidden = !lineNumHidden;
    });

    /****************
     * Side Section *
     ****************/

    // Go back to upper level in the directory tree
    $(document).on("click", ".sideSection_breadcrumb .breadcrumb a.breadcrumb_item", function (event) {
        var target = $(event.target);
        var path = target.attr("path");
        if (target.parent().is(':last-child')) {
            return;
        }
        target.parent().nextAll("li").remove();
        adjustBreadcrumb(function () {
            changeRootHelper(path);
        });
    });

    // Go one level upper in the directory tree
    $(".breadcrumb .breadcrumb_upper").click(function () {
        var path = $(".sideSection_breadcrumb").attr("current-path");
        path = path.substring(0, path.length - 1);
        path = path.substring(0, path.lastIndexOf("/"));
        $(".sideSection_breadcrumb .breadcrumb li").last().remove();
        changeRootHelper(path);
        adjustBreadcrumb();
    });

    // Request for deeper directory content
    $(document).on("click", ".isDir", function (event) {
        loadDirHelper(event.target);
    });

    // Request for file content
    $(document).on("click", ".isFile", function (event) {
        loadFileHelper(event.target);
    });

    // Delete the input block when it lost focus
    $(document).on('blur', "#newFileNameInput", function () {
        $("li.newFileEntry").remove();
    });
    $(document).on('blur', "#newDirNameInput", function () {
        $("li.newDirEntry").remove();
    });
    $(document).on('blur keyup', "#replaceFileNameInput", function (event) {
        if (event.type === 'focusout' && (!event.keyCode || event.keyCode !== 13)) {
            $("#replaceFileNameInput+a.isFile").css("display", "block");
            $("li #replaceFileNameInput").remove();
        }
    });

    // Detect if Enter key is pressed, save the file name and try writing to remote server
    $(document).on('keydown', "#newFileNameInput", function (event) {
        if (event.keyCode === 13) {
            var val = $("#newFileNameInput").val();
            var newLi = $(".mainContainer .newFileEntry");
            var parent = newLi.parent();
            var indent = newLi.attr("indent");
            var path;
            if (indent > 0) {
                var parentPointer = parent.prev();
                path = parentPointer.attr("id").substring(4) + "/" + val;
            } else {
                path = val;
            }
            path = $(".sideSection_breadcrumb").attr("current-path") + path;
            if ($("a[path='" + path + "']").length) {
                alert("You cannot have two files in the same directory with identical name.");
                newLi.remove();
                return;
            }
            saveChange("", path, function (status) {
                if (!status) {
                    alert("Create new file failed.");
                    return;
                }
                else {
                    var id = "file_" + path.substring(1).split(".").join("_").split("/").join("_");
                    newLi.empty();
                    var newLink = $("<a>").attr({
                        href: "#",
                        path: path
                    }).addClass("isFile").text(val);
                    newLink.prepend($("<span>").addClass("glyphicon glyphicon-file").attr("aria-hidden", "true"));
                    newLi.attr("id", id).append(newLink);
                    newLi.removeClass("newFileEntry");
                    var existed = parent.children("li:has('.isFile')");
                    for (var i = 0; i < existed.length; i++) {
                        if (existed[i].id > id) {
                            $(existed[i]).before(newLi);
                            loadFileHelper(newLi.children("a"));
                            return;
                        }
                    }
                    parent.append(newLi);
                    loadFileHelper(newLi.children("a"));
                }
            });
        }
        else if (event.keyCode === 27) {
            $("#newFileNameInput").blur();
        }
    });
    // Detect if Enter key is pressed, save the directory name and try writing to remote server
    $(document).on('keydown', "#newDirNameInput", function (event) {
        if (event.keyCode === 13) {
            var val = $("#newDirNameInput").val();
            var newLi = $(".mainContainer .newDirEntry");
            var parent = newLi.parent();
            var indent = newLi.attr("indent");
            var path;
            if (indent > 0) {
                var parentPointer = parent.prev();
                path = parentPointer.attr("id").substring(4) + "/" + val;
            } else {
                path = val;
            }
            path = $(".sideSection_breadcrumb").attr("current-path") + path;
            if ($("a[path='" + path + "']").length) {
                alert("You cannot have two directories under the same directory with identical name.");
                newLi.remove();
                return;
            }
            mkdir(path, function (status) {
                if (!status) {
                    alert("Create new directory failed.");
                    return;
                }
                else {
                    var id = "dir_" + path.substring(1).split(".").join("_").split("/").join("_");
                    newLi.empty();
                    var newLink = $("<a>").attr({
                        href: "#",
                        path: path
                    }).addClass("isDir").text(val);
                    newLink.prepend($("<span>").addClass("glyphicon glyphicon-menu-right").attr("aria-hidden", "true"));
                    newLi.attr("id", id).append(newLink);
                    newLi.removeClass("newDirEntry");
                    var existed = parent.children("li:has('.isDir')");
                    for (var i = 0; i < existed.length; i++) {
                        if (existed[i].id > id) {
                            $(existed[i]).before(newLi);
                            return;
                        }
                    }
                    parent.append(newLi);
                }
            });
        }
        else if (event.keyCode === 27) {
            $("#newDirNameInput").blur();
        }
    });
    // Detect if Enter key is pressed, call the renameFile function with data
    $(document).on('keydown', "#replaceFileNameInput", function (event) {
        if (event.keyCode === 13) {
            var newName = $("#replaceFileNameInput").val();
            var path = $("#replaceFileNameInput+a.isFile").attr("path");
            var newPath = path.substring(0, path.lastIndexOf('/') + 1) + newName;
            var open = -1;
            var modified = false;
            var content = "";
            for (var i = 0; i < activeFile.length; i++) {
                if (path === activeFile[i].path) {
                    open = i;
                    if (activeFile[i].type === "text") {
                        if (activeFile[i].content !== modifiedFile[i].content) {
                            modified = true;
                        }
                    }
                    content = activeFile[i].content;
                    break;
                }
            }
            if (modified) {
                alert("You have unsaved modification.");
                $("#replaceFileNameInput+a.isFile").css("display", "block");
                $("li #replaceFileNameInput").remove();
                return;
            }
            if (content.length === 0) { // Content never loaded
                return loadFile(path, function (status, data) {
                    if (status) {
                        return alert(status);
                    }
                    renameFile(path, newPath, data, function (success) {
                        if (success) {
                            renameHelper(open, path, newPath);
                        }
                    });
                });
            }
            renameFile(path, newPath, content, function (success) {
                if (success) {
                    renameHelper(open, path, newPath);
                }
            });
        }
        else if (event.keyCode === 27) {
            $("#replaceFileNameInput").blur();
        }
    });

    // Click on buttons on "Recently Visited" bar
    // Either hide the whole "recently visited" section, or erase all records
    $("#recentlyVisited h6 span").click(function () {
        if ($(this).hasClass("eraseVisitedList")) {
            visitedList.length = 0;
            $("#recentlyVisited ul").empty();
            return;
        }
        if ($(this).hasClass("glyphicon-menu-down")) {
            $(this).removeClass("glyphicon-menu-down").addClass("glyphicon-menu-up").attr("title", "Open Visited List");
            $("#recentlyVisited").css("height", "25px");
            $("#fileList").css("height", "100%").css("height", "-=25px");
            return;
        }
        if ($(this).hasClass("glyphicon-menu-up")) {
            $(this).removeClass("glyphicon-menu-up").addClass("glyphicon-menu-down").attr("title", "Close Visited List");
            $("#recentlyVisited").css("height", "40%");
            $("#fileList").css("height", "60%");
        }
    });

    // Click on item in recently visited list to open the file again/switch to the corresponding tab
    $(document).on("click", ".visitedFile", function (event) {
        var _this = $(event.target);
        if (_this.is("span")) {
            _this = _this.parent();
        }
        var path = _this.text();
        if ($("a.isFile[path='/" + path + "']").length) {
            return loadFileHelper($("a.isFile[path='/" + path + "']"));
        }
        loadFileHelper("/" + path);
    });

    // Open right click menu on side bar
    $("#fileList").bind("contextmenu", function (event) {
        event.preventDefault();
        // Hide the set root option if the target is a file
        if ($(event.target).hasClass("isDir") || $(event.target).parent().hasClass("isDir")) {
            $(".sideBarRightClick .sideBarRightClick_root").parent().css("display", "list-item");
        }
        else {
            $(".sideBarRightClick .sideBarRightClick_root").parent().css("display", "none");
        }
        var path = $(event.target).attr("path");
        if ($(event.target).is("span")) {
            path = $(event.target).parent().attr("path");
        }
        $(".sideBarRightClick").toggleClass("open").css({ top: event.pageY + "px", left: event.pageX + "px" }).attr("target", path);
    });

    // Open the target file/directory
    $(".sideBarRightClick .sideBarRightClick_open").click(function (event) {
        $(".sideBarRightClick").removeClass("open");
        var target = $(".directoryList a[path='" + $(".sideBarRightClick").attr("target") + "']");
        if (target.hasClass("isDir")) {
            loadDirHelper(target);
        }
        else {
            loadFileHelper(target);
        }
    });

    // Delete the target file/directory
    $(".sideBarRightClick .sideBarRightClick_delete").click(function (event) {
        $(".sideBarRightClick").removeClass("open");
        $("#DeleteFileConfirm").modal("show");

        // Confirm to delete file
        $("#DeleteFileConfirm button.btn-success").unbind('click').click(function () {
            var path = $(".sideBarRightClick").attr("target");
            var id = "file_" + path.substring(1).split(".").join("_").split("/").join("_");
            if ($(".directoryList li#" + id + "").length === 0) {
                id = "dir_" + id.substring(5);
                if ($("div.collapse#" + id).children().length > 0) {
                    return alert("You cannot delete a directory that contains files.");
                }
            }
            for (var i = 0; i < activeFile.length; i++) {
                if (activeFile[i].path && activeFile[i].path === path) {
                    var recentVisit = $("#recentlyVisited ul").children("li:contains(" + path.substring(1) + ")");
                    var index = recentVisit.index();
                    recentVisit.remove();
                    visitedList.splice(index, 1);
                    break;
                }
            }
            deleteFile(path, id);
            deleteTab(i, $(".titleBar li[index='" + i + "']"));
        });
    });

    // Add input box for new file name
    $(".sideBarRightClick .sideBarRightClick_rename").click(function (event) {
        $(".sideBarRightClick").removeClass("open");

        // Replace the name with an input tag
        var path = $(".sideBarRightClick").attr("target");
        var parentLi = $(".directoryList li a[path='" + path + "']").parent();
        if (parentLi.children("a").hasClass("isDir")) {
            return alert("You cannot rename a directory.");
        }
        parentLi.children("a").css("display", "none");
        var input = $("<input>").attr({
            type: "text",
            id: "replaceFileNameInput"
        });
        var indentPx = parseInt(parentLi.attr("indent")) * 20 + 12;
        input.css("width", (parentLi.outerWidth() - indentPx) + "px");
        input.css("marginLeft", indentPx + "px");
        input.prependTo(parentLi);
        input.focus();
    });

    // Call the function to create a new file
    $(".sideBarRightClick .sideBarRightClick_newFile").click(function (event) {
        rightClickSelect(function () {
            createNewItem("File");
        });
    });

    // Call the function to create a new directory
    $(".sideBarRightClick .sideBarRightClick_newDir").click(function (event) {
        rightClickSelect(function () {
            createNewItem("Dir");
        });
    });

    // Change the root directory for file list, only show the content of a sub directory
    $(".sideBarRightClick .sideBarRightClick_root").click(function (event) {
        $(".sideBarRightClick").removeClass("open");
        var path = $(".sideBarRightClick").attr("target");
        // Change the breadcrumb on the top
        var currentPath = $(".sideSection_breadcrumb").attr("current-path");
        if (path.indexOf(currentPath) !== 0) {
            throw new Error("Path does not match");
        }
        var parsedPath = path.replace(currentPath, '');
        parsedPath = parsedPath.split("/");
        for (var i = 0; i < parsedPath.length; i++) {
            var li = $("<li>").append($("<a href='#'>").attr("path", "/" + parsedPath.slice(0, i + 1).join("/")).addClass("breadcrumb_item").text(parsedPath[i]));
            li.appendTo($(".sideSection_breadcrumb .breadcrumb"));
        }
        adjustBreadcrumb(function () {
            changeRootHelper(path);
        });
    });

    /******************
     * Editor Section *
     ******************/

    // Switch between files by clicking on tabs
    $(document).on("click", ".titleBar .nav a", function (event) {
        var _this = $(event.target);
        var parentLi = _this.parent();
        if (!parentLi.hasClass("activeTab")) {
            var position = parseInt(parentLi.attr("index"));
            $(".activeTab").removeClass("activeTab");
            parentLi.addClass("activeTab");
            history.currentPath = _this.text();
            activeTabPos = position;
            var fileName = _this.text().substring(1).split(".").join("_").split("/").join("_");
            $(".fileSelected").removeClass("fileSelected");
            $(".directorySelected").removeClass("directorySelected");
            var selectedLi = $("li#file_" + fileName);
            selectedLi.addClass("fileSelected");
            selectedLi.parent().prev().addClass("directorySelected");
            codeMirror = cmInstanceList[position];
            $(".editorWrap .CodeMirror.open").removeClass("open");
            $(".editorWrap .CodeMirror:eq(" + position + ")").addClass("open");
            if (!previewPanelHidden) {
                previewer.preview(codeMirror);
            }
        }
    });

    // Click on x button to close tab
    $(document).on("click", ".closeTab", function (event) {

        var _this = $(event.target);
        var parentLi = _this.parent();
        var position = parseInt(parentLi.attr("index"));
        // Check if the content has been changed first
        if (activeFile[position].type === "text" && activeFile[position].content !== modifiedFile[position].content) {
            $("#CloseModifiedTab").modal("show");

            // Confirm to discard changes
            $("#CloseModifiedTab button.btn-success").unbind('click').click(function () {
                deleteTab(position, parentLi);
            });
        }
        else {// Content has never been changed
            deleteTab(position, parentLi);
        }
    });

    // Click on items in hiddenTab dropdown
    // Either switch to one of the open file, or close all tabs
    $(document).on("click", ".hiddenList li", function (event) {
        var _this = $(event.target);
        if (_this.hasClass("closeAllTabs")) {
            // close all open tabs
            modifiedFile.splice(0, modifiedFile.length);
            activeFile.splice(0, activeFile.length);
            $(".titleBar ul.nav").empty();
            $(".titleBar ul.hiddenList li:not(:has('.closeAllTabs'))").remove();
            $(".fileSelected").removeClass("fileSelected");
            hiddenTabSize.splice(0, hiddenTabSize.length);
            activeTabPos = -1;
            history.historyList = {};
            tabTotalLength = $(".hiddenTabs").outerWidth();
            cmInstanceList.splice(1, cmInstanceList.length);
            codeMirror = cmInstanceList[0];
            $(".editorWrap .CodeMirror").not(":first").remove();
            $(".editorWrap .CodeMirror:eq(0)").addClass("open");
            codeMirror.getDoc().setValue("");
            if (!previewPanelHidden) {
                previewer.preview(codeMirror);
            }
            codeMirror.getDoc().markClean();
        }
        else {
            // open one of the hidden tabs
            activeTabPos = _this.parent().attr("index");
            var path = _this.attr("path").substring(1);
            $(".activeTab").removeClass("activeTab");
            if ($("a.isFile[path='/" + path + "']").length) {
                return loadFileHelper($("a.isFile[path='/" + path + "']"));
            }
            loadFileHelper("/" + path);
        }
    });

    // Handle content changes in codeMirror
    $(document).on('keyup', '.editorWrap .CodeMirror.open', function () {
        checkForChanges();
        if (!previewPanelHidden) {
            if (previewer.previewTimer) {
                clearTimeout(previewer.previewTimer);
            }
            previewer.previewTimer = setTimeout(previewer.preview(codeMirror), 200);
        }
    });

    /******************
     * Whole Document *
     ******************/

    // Close the right cilck menu when click elsewhere
    $(document).bind("mousedown", function (event) {
        if ($(".sideBarRightClick").has($(event.target)).length <= 0) {
            if ($(".sideBarRightClick").hasClass("open")) {
                $(".sideBarRightClick").removeClass("open");
            }
        }
        if ($(".nav .dropdown").has($(event.target)).length <= 0) {
            if ($(".nav .dropdown").hasClass("open")) {
                $(".nav .dropdown").removeClass("open");
            }
        }
    });

    // Drag the dragbar between editor and preview to adjust their widths
    $(".verticalDragBar, .horizontalDragBar").mousedown(function (event) {
        event.preventDefault();
        dragging = true;
        var target = $(event.target);
        var dragLeftIgnore = target.attr("drag-left-ignore");
        var dragTopIgnore = target.attr("drag-top-ignore");
        var dragGhostPosition = target.attr("drag-ghost-position");
        var dragLeft = target.attr("drag-left");
        var dragRight = target.attr("drag-right");
        var ghostDragBar;
        ghostDragBar = $("<div>").addClass("ghostDragBar").attr({
            "drag-left": dragLeft,
            "drag-right": dragRight,
            "drag-left-ignore": dragLeftIgnore,
            "drag-top-ignore": dragTopIgnore,
            "drag-ghost-position": dragGhostPosition
        }).appendTo("." + dragGhostPosition);
        if (target.hasClass("verticalDragBar")) {
            ghostDragBar.css({
                "left": target.position().left,
                "top": "0px"
            });
        }
        else {
            ghostDragBar.css({
                "top": target.position().top,
                "left": "0px"
            });
        }
        $(".previewWrap .iframeCover").css("display", "block");

        $(document).mousemove(function (event) {
            if (target.hasClass("verticalDragBar")) {
                if (dragLeftIgnore) {
                    ghostDragBar.css("left", event.pageX - $("." + dragLeftIgnore).outerWidth() - 1);
                }
                else {
                    ghostDragBar.css("left", event.pageX - 1);
                }
            }
            else {
                ghostDragBar.css("top", event.pageY - $("." + dragTopIgnore).outerHeight());
            }
        });
    });

    // Set the new width of editor and preview, adjust tabs if necessary
    $(document).mouseup(function (event) {
        if (dragging) {
            $(".previewWrap .iframeCover").css("display", "none");
            var percentag;
            var restPercentage;
            var ghost = $('.ghostDragBar');
            var dragLeft = ghost.attr("drag-left");
            var dragRight = ghost.attr("drag-right");
            var dragLeftIgnore = ghost.attr("drag-left-ignore");
            var dragTopIgnore = ghost.attr("drag-top-ignore");
            var dragGhostPosition = ghost.attr("drag-ghost-position");
            if (!dragLeftIgnore) { // draggable bar between fileList and mainSection
                percentage = ((event.pageX) / $("." + dragGhostPosition).outerWidth()) * 100;
                restPercentage = 100 - percentage;
                $('.' + dragLeft).css("width", percentage + "%");
                $('.' + dragRight).css("width", restPercentage + "%");
            }
            else if ($(this).width() > 991) {
                percentage = ((event.pageX - $("." + dragLeftIgnore).outerWidth()) / $("." + dragGhostPosition).outerWidth()) * 100;
                restPercentage = 100 - percentage;
                $('.' + dragLeft).css("width", percentage + "%");
                $('.' + dragRight).css("width", restPercentage + "%");
            }
            else {
                percentage = ((event.pageY - $("." + dragTopIgnore).outerHeight()) / $("." + dragGhostPosition).outerHeight()) * 100;
                restPercentage = 100 - percentage;
                $('.' + dragLeft).css("height", percentage + "%");
                $('.' + dragRight).css("height", restPercentage + "%");
            }
            ghost.remove();
            $(document).unbind('mousemove');
            dragging = false;
            titleBarLengthMaximum = $(".titleBar").outerWidth() - 20;
            while (tabTotalLength > titleBarLengthMaximum) {
                tabTotalLength = hideTab(tabTotalLength, titleBarLengthMaximum, parseInt($(".titleBar .nav li").last().attr("index")), hiddenTabSize);
            }
            while (hiddenTabSize.length > 0 &&
                tabTotalLength + hiddenTabSize[hiddenTabSize.length - 1] < titleBarLengthMaximum) {
                tabTotalLength += hiddenTabSize[hiddenTabSize.length - 1];
                showTab();
                hiddenTabSize.pop();
            }
            codeMirror.refresh();
            adjustBreadcrumb();
        }
    });

    // Ask for confirmation before user leaves the page if there are unsaved contents
    // Use browser's default confirmation box
    $(window).on("beforeunload", function () {
        if (contentModified) {
            return "Are you sure to leave this page? There are unsaved contents.";
        }
    });

    // Adjust the draggable bar to fit in the responsive page when window resize or page load
    $(window).resize(function () {
        if ($(this).width() < 992) {
            $(".editorSection").width("");
            $(".verticalDragBar[drag-left-ignore='sideSection']").removeClass("verticalDragBar").addClass("horizontalDragBar");
        }
        else {
            $(".editorSection").height("");
            $(".horizontalDragBar[drag-left-ignore='sideSection']").removeClass("horizontalDragBar").addClass("verticalDragBar");
        }
        codeMirror.refresh();
        adjustBreadcrumb();
    }).resize();
});
