var history_template = Handlebars.compile($("#history-template").html());
var error_template = Handlebars.compile($("#history-error-template").html());
var history_div = $("#history-div");

airport_history = function airport_history (airport, date) {
    $.getJSON("/historydata", {"airport": airport, "date": date})
        .done(function (data) {
            history_div.html(history_template(data));
        })
        .fail(function () {
            history_div.html(error_template());
        })
}
