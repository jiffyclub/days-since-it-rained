var dsir_tpl = Handlebars.compile($("#dsir-template").html());
var dsir_event_tpl = Handlebars.compile($("#dsir-event-template").html());
var no_location_tpl = Handlebars.compile($("#no-location-template").html());
var no_rain_tpl = Handlebars.compile($("#no-rain-template").html());
var dsir_div = $("#dsir-div");

find_rain = function find_rain (address, more_than) {
    $.getJSON("/data", {"address": address, "threshold": more_than})
        .done(function (data) {
            if (data.precip > 0) {
                dsir_div.html(dsir_tpl(data));
            } else {
                dsir_div.html(dsir_event_tpl(data));
            }
        })
        .fail(function (jqxhr, textStatus, error) {
            var msg = jqxhr.responseJSON.message;
            if (msg === "no results" || msg === "no location") {
                dsir_div.html(no_location_tpl());
            } else if (msg === "no rain") {
                dsir_div.html(no_rain_tpl());
            } else {
                dsir_div.html("<p>Unknown error!</p>")
            }
        })
}
