import logging

from flask import (
    Flask, abort, jsonify, redirect, url_for, render_template, request)

import dsir
from dsirexceptions import (
    ZeroResultsError, GeocodeError, AirportError, RainError)

app = Flask(__name__)


def configure_logging():
    lg = logging.getLogger('dsir')
    lg.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '%(asctime)s|%(name)s|%(levelname)s|%(message)s')
    ch.setFormatter(formatter)

    lg.addHandler(ch)
configure_logging()


def check_threshold(thresh):
    try:
        more_than = float(thresh)
    except ValueError:
        return 0
    else:
        return more_than


@app.route('/')
def index():
    # render index
    return render_template('index.html')


@app.route('/faq')
def faq():
    return render_template('faq.html')


@app.route('/dsir')
def days():
    # render info page
    address = request.args.get('address')
    if not address:
        return abort(404)
    more_than = check_threshold(request.args.get('threshold', 0)) or 0
    return render_template(
        'dsir.html', address=address, more_than=more_than)


@app.route('/search', methods=['POST'])
def search():
    address = request.form['address']
    threshold = request.form['threshold']
    return redirect(url_for('days', address=address, threshold=threshold))


@app.route('/data')
def data():
    # return JSON rain data
    address = request.args.get('address')
    if not address:
        return app.make_response(
            (jsonify(status='error', message='no address'), 400))

    more_than = check_threshold(request.args.get('threshold', 0))

    try:
        days, rain_day, loc, airport = dsir.days_since_it_rained(
            address, more_than=more_than)
    except ZeroResultsError:
        return app.make_response(
            (jsonify(status='error', message='no results'), 404))
    except (GeocodeError, AirportError):
        return app.make_response(
            (jsonify(status='error', message='no location'), 404))
    except RainError:
        return app.make_response(
            (jsonify(status='error', message='no rain'), 404))
    else:
        return app.make_response(jsonify(
            status='ok',
            dsir=days,
            address=loc.address,
            date=rain_day.date.isoformat(),
            precip=rain_day.precip,
            more_than=more_than,
            wulink=dsir.daily_history_url(airport, rain_day.date)))


if __name__ == '__main__':
    app.run(debug=True)
