$(document).ready(function () {
    $(".markupCheatsheet").load('template/markupCheatsheet.html');

    $(".cheatsheetBtn").click(function () {
        $(".markupCheatsheet").addClass("open");
    });

    $(document).on('click', '.markup_closeBtn', function () {
        $(".markupCheatsheet").removeClass("open");
        $(".markup_navPills li.active").removeClass("active");
        $(".markup_tabContent div.active").removeClass("active");
        $(".markup_navPills li").first().addClass("active");
        $(".markup_tabContent div").first().addClass("active");
    });

    $(document).on('click', '.markup_navPills li', function (event) {
        var _this = $(event.target);
        $(".markup_navPills li.active").removeClass("active");
        _this.parent().addClass("active");
    });

    $(document).on('click', '.markup_linkToOtherPanes', function (event) {
        event.preventDefault();
        var _this = $(event.target);
        var link = _this.attr("href");
        $(".markup_navPills a[href='" + link + "']").tab("show");
    });
});