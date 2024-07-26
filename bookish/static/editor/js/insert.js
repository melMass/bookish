$(document).ready(function () {
    var codeMirror = $('.CodeMirror')[0].CodeMirror;
    $(".toolIcon.glyphicon-camera").click(function () {
        if ($(".titleBar .nav").children("li").length) {
            var doc = codeMirror.getDoc();
            doc.replaceSelection("[Image:");
            doc.replaceSelection("]", "start");
            $(".titleBar .activeTab").addClass("contentModified");
            codeMirror.focus();
        }
    });
    $(".toolIcon.glyphicon-info-sign").click(function () {
        if ($(".titleBar .nav").children("li").length) {
            var doc = codeMirror.getDoc();
            doc.replaceSelection("NOTE:\n  ");
            $(".titleBar .activeTab").addClass("contentModified");
            codeMirror.focus();
        }
    });
    $(".toolIcon.glyphicon-plus-sign").click(function () {
        if ($(".titleBar .nav").children("li").length) {
            var doc = codeMirror.getDoc();
            doc.replaceSelection("[Icon:");
            doc.replaceSelection("]", "start");
            $(".titleBar .activeTab").addClass("contentModified");
            codeMirror.focus();
        }
    });
    $(document).on("click", "a.isFile, a.visitedFile, .titleBar .nav a, span.closeTab, .hiddenList li a", function (event) {
        setTimeout(function () {
            codeMirror = $('.CodeMirror.open')[0].CodeMirror;
        }, 50);

    });
});