// Helper function
// Check whether the toolbar is in replace mode
function checkReplaceMode() {
    var inputGroup = $(".toolBar .input-group");
    if (!inputGroup.hasClass("replaceMode")) {
        if (!inputGroup.hasClass("searchMode") || !inputGroup.children("#toolBar_search").val()) {
            inputGroup.addClass("searchMode replaceMode");
            inputGroup.children("#toolBar_search").focus();
            return false;
        }
        inputGroup.addClass("replaceMode");
        inputGroup.children("#toolBar_replace").focus();
        return false;
    }
    return true;
}
// Check whether the toolbar is in search mode
function checkSearchMode() {
    var inputGroup = $(".toolBar .input-group");
    if (!inputGroup.hasClass("searchMode") || !inputGroup.children("#toolBar_search").val()) {
        inputGroup.addClass("searchMode");
        inputGroup.children("#toolBar_search").focus();
        return false;
    }
    return true;
}

$(document).ready(function () {
    var codeMirror = $('.CodeMirror.open')[0].CodeMirror;
    var query = "";
    var caseSensitive = true;
    var cursor = codeMirror.getSearchCursor(query, undefined, caseSensitive);
    var replaceStr = "";
    var totalInstance = 0;

    // Click detected on NavBar/Edit/Find, open find input field on toolBar
    $(".editMenu_find").click(function () {
        var inputGroup = $(".toolBar .input-group");
        if (inputGroup.hasClass("searchMode replaceMode")) {
            return inputGroup.removeClass("replaceMode");
        }
        inputGroup.addClass("searchMode");
    });

    // Click detected on NavBar/Edit/Find Previous, get the match ahead of current position
    $(".editMenu_findPrev").click(function () {
        $(".toolBar_prev").trigger("click");
    });

    // Click detected on NavBar/Edit/Find Next, get next match in the file
    $(".editMenu_findNext").click(function () {
        $(".toolBar_next").trigger("click");
    });

    // Click detected on NavBar/Edit/Replace, 
    // open replace input field if not exist, replace the selected text otherwise
    $(".editMenu_replace").click(function () {
        if (checkReplaceMode()) {
            $(".toolBar_replaceBtn").trigger("click");
        }
    });

    // Click detected on NavBar/Edit/Replace All, 
    // open replace input field if not exist, replace all matches
    $(".editMenu_replaceAll").click(function () {
        if (checkReplaceMode()) {
            cursor = codeMirror.getSearchCursor(query, { line: codeMirror.firstLine(), ch: 0 }, caseSensitive);
            cursor.findNext();
            while (cursor.from()) {
                cursor.replace(replaceStr);
                cursor.findNext();
            }
            if (!$(".activeTab").hasClass("contentModified") && query !== "") {
                $(".activeTab").addClass("contentModified");
            }
        }
    });

    // Click detected on NavBar/Edit/Find All, select all matches
    $(".editMenu_findAll").click(function () {
        if (!checkSearchMode()) {
            return;
        }
        cursor.findNext();
        if (!cursor.from()) {
            cursor = codeMirror.getSearchCursor(query, { line: codeMirror.firstLine(), ch: 0 }, caseSensitive);
            cursor.findNext();
        }
        var selections = [];
        while (cursor.from()) {
            selections.push({ anchor: cursor.from(), head: cursor.to() });
            cursor.findNext();
        }
        codeMirror.setSelections(selections);
    });

    // Click detected on NavBar/Edit/Undo, undo the change if applicable
    $(".editMenu_undo").click(function () {
        if (!codeMirror.getDoc().isClean()) {
            codeMirror.execCommand("undo");
        }
    });

    // Click detected on NavBar/Edit/Redo, redo the change if applicable
    $(".editMenu_redo").click(function () {
        codeMirror.execCommand("redo");
    });


    // Click detected on toolbar search button, open find input field on toolBar
    $(".toolIcon.glyphicon-search").click(function () {
        var inputGroup = $(".toolBar .input-group");
        if (inputGroup.hasClass("searchMode replaceMode")) {
            return inputGroup.removeClass("replaceMode");
        }
        inputGroup.toggleClass("searchMode");
    });

    // Click detected on toolbar replace button, 
    // open replace input field if not exist, replace the selected text otherwise
    $(".toolBar_replaceBtn").click(function () {
        var inputGroup = $(".toolBar .input-group");
        if (!inputGroup.hasClass("replaceMode")) {
            return inputGroup.addClass("replaceMode");
        }
        cursor.findNext();
        if (!cursor.from()) {
            cursor = codeMirror.getSearchCursor(query, { line: codeMirror.firstLine(), ch: 0 }, caseSensitive);
            if (!cursor.findNext()) {
                return;
            }
        }
        cursor.replace(replaceStr);
        codeMirror.setCursor(cursor.to());
        codeMirror.focus();
        if (!$(".activeTab").hasClass("contentModified") && query !== "") {
            $(".activeTab").addClass("contentModified");
        }
    });

    // Click detected on toolbar findnext button, get the next match in the text
    $(".toolBar_next").click(function () {
        var success = cursor.findNext();
        if (success) {
            codeMirror.setSelection(cursor.from(), cursor.to());
        }
        else {
            cursor = codeMirror.getSearchCursor(query, { line: codeMirror.firstLine(), ch: 0 }, caseSensitive);
            if (cursor.findNext()) {
                codeMirror.setSelection(cursor.from(), cursor.to());
            }
        }
        codeMirror.focus();
    });

    // Click detected on toolbar findprev button, get the previous match in the text
    $(".toolBar_prev").click(function () {
        var success = cursor.findPrevious();
        if (success) {
            codeMirror.setSelection(cursor.from(), cursor.to());
        }
        else {
            cursor = codeMirror.getSearchCursor(query, { line: codeMirror.lastLine(), ch: 0 }, caseSensitive);
            if (cursor.findPrevious()) {
                codeMirror.setSelection(cursor.from(), cursor.to());
            }
        }
        codeMirror.focus();
    });

    // Change detected on value in search input field, reset the cursor with new query
    $("#toolBar_search").change(function () {
        query = $(this).val();
        cursor = codeMirror.getSearchCursor(query, undefined, caseSensitive);
    });

    // Change detected on value in replace input field, reset the replace string
    $("#toolBar_replace").change(function () {
        replaceStr = $(this).val();
    });
    
    // Change detected on toolbar case sensitive button, switch the case sensitive setting
    $(".toolBar_case").click(function () {
        caseSensitive = !caseSensitive;
        cursor = codeMirror.getSearchCursor(query, undefined, caseSensitive);
        if (caseSensitive) {
            $(this).removeClass("selectedBtn");
            return;
        }
        $(this).addClass("selectedBtn");
    });

    $(document).on("click", "a.isFile, a.visitedFile, .titleBar .nav a, span.closeTab, .hiddenList li a", function (event) {
        setTimeout(function () {
            codeMirror = $('.CodeMirror.open')[0].CodeMirror;
            codeMirror.setOption("extraKeys", keymap);
            cursor = codeMirror.getSearchCursor(query, undefined, caseSensitive);
        }, 50);

    });

    // Duplicate the content on current line and inset it above/below the current line
    var duplicateLine = function (cm, direction) {
        var curLine = codeMirror.getCursor().line;
        var curCh = codeMirror.getCursor().ch;
        var lineVal = codeMirror.getLine(curLine);
        if (direction === "down") {
            cm.execCommand("goLineEnd");
            cm.getDoc().replaceSelection("\n" + lineVal);
            cm.setCursor({ line: curLine + 1, ch: curCh });
        }
        else {
            cm.execCommand("goLineStart");
            cm.getDoc().replaceSelection(lineVal + "\n");
            cm.setCursor({ line: curLine, ch: curCh });
        }
    };

    var smartBs = function (cm) {
        var tab = cm.getOption("indentUnit");
        var start = cm.getCursor("start");
        var end = cm.getCursor("end");
        if (start.line == end.line && start.ch == end.ch && start.ch > 0) {
            var point = start.ch - 1;
            var line = cm.getLine(start.line);
            var count = 0;
            while (count < tab && point >= 0 && line.charAt(point) === " ") {
                cm.execCommand("delCharBefore");
                count += 1;
                point -= 1;
            }
            if (count === 0) {
                cm.execCommand("delCharBefore");
            }
        } else {
            cm.execCommand("delCharBefore");
        }
    };

    // Set keymap
    var keymap = {
        // Windows Keymap
        "Ctrl-F": checkSearchMode,
        "Shift-Ctrl-F": checkReplaceMode,
        "Ctrl-G": function () {
            $(".toolBar_next").trigger("click");
        },
        "Shift-Ctrl-G": function () {
            $(".toolBar_prev").trigger("click");
        },
        "Shift-Ctrl-R": function () {
            $(".editMenu_replaceAll").trigger("click");
        },
        "Ctrl-Backspace": function (cm) {
            cm.execCommand("delWordBefore");
        },
        "Ctrl-S": function () {
            $(".nav.navbar-nav .fileMenu_save").trigger("click");
        },
        "Shift-Ctrl-Down": function (cm) {
            duplicateLine(cm, "down");
        },
        "Shift-Ctrl-Up": function (cm) {
            duplicateLine(cm, "up");
        },
        "Ctrl-Z": function (cm) {
            if (!codeMirror.getDoc().isClean()) {
                codeMirror.execCommand("undo");
            }
        },
        // macOS Keymap
        "Cmd-F": checkSearchMode,
        "Shift-Cmd-F": checkReplaceMode,
        "Cmd-G": function () {
            $(".toolBar_next").trigger("click");
        },
        "Shift-Cmd-G": function () {
            $(".toolBar_prev").trigger("click");
        },
        "Cmd-Backspace": function (cm) {
            cm.execCommand("delWordBefore");
        },
        "Shift-Cmd-R": function () {
            $(".editMenu_replaceAll").trigger("click");
        },
        "Cmd-S": function () {
            $(".nav.navbar-nav .fileMenu_save").trigger("click");
        },
        "Shift-Cmd-Down": function (cm) {
            duplicateLine(cm, "down");
        },
        "Shift-Cmd-Up": function (cm) {
            duplicateLine(cm, "up");
        },
        "Cmd-Z": function (cm) {
            if (!codeMirror.getDoc().isClean()) {
                codeMirror.execCommand("undo");
            }
        },
        // both
        "Alt-Backspace": function (cm) {
            cm.execCommand("delLineLeft");
        },

        "Tab": "indentMore",
        "Shift-Tab": "indentLess",
        "Backspace": smartBs
    };
    codeMirror.setOption("extraKeys", keymap);

});
