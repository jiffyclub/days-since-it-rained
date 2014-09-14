import csv
import logging
import os
import re
from collections import namedtuple
from datetime import date, datetime, timedelta
from io import StringIO

import requests

from dsirexceptions import (
    ZeroResultsError, GeocodeError, AirportError, RainError)

logger = logging.getLogger(__name__)


Location = namedtuple('Location', ('address', 'lat', 'lng'))

sess = requests.Session()
sess.headers.update({'user-agent': 'dayssinceitrained.info'})


def address_to_geodata(addr):
    """
    Convert an address to a dict of geodata via the Google Maps API.

    Parameters
    ----------
    addr : str

    Returns
    -------
    location : namedtuple
        With .address, .lat, and .lng fields.

    """
    baseurl = 'https://maps.googleapis.com/maps/api/geocode/json'
    apikey = os.environ['GMAPSKEY']
    params = {'key': apikey, 'address': addr}

    logger.debug('geocoding address: {!r}'.format(addr))

    resp = requests.get(baseurl, params=params)
    resp.raise_for_status()
    results = resp.json()

    if results['status'] != 'OK':
        if results['status'] == 'ZERO_RESULTS':
            msg = 'no results found for address {!r}'.format(addr)
            logger.error(msg)
            raise ZeroResultsError(msg)
        else:
            msg = 'error occurred with status: {!r} and message: {!r}'.format(
                  results['status'], results.get('error_message'))
            logger.error(msg)
            raise GeocodeError(msg)
    else:
        res = results['results'][0]

    address = res['formatted_address']
    lat = res['geometry']['location']['lat']
    lng = res['geometry']['location']['lng']

    return Location(address, lat, lng)


def get_airport_code(lat, lng):
    """
    Get the code for the airport nearest a lat/lng location.

    """
    baseurl = (
        'http://www.wunderground.com/cgi-bin/findweather/getForecast'
        '?query={},{}').format(lat, lng)
    resp = sess.get(baseurl)
    resp.raise_for_status()

    code = re.search(r'/history/airport/([a-zA-Z]{4})/', resp.text)

    if not code:
        raise AirportError(
            'Could not find airport code for lat/lng: {}, {}'.format(lat, lng))

    return code.group(1)


def one_year_back(dt):
    """
    Return a date minus 365 days.

    """
    return dt - timedelta(days=365)


HistoryDay = namedtuple(
    'HistoryDay', ('date', 'precip', 'events', 'min_temp', 'max_temp'))


def history_year(dt, airport):
    """
    Get a year of history going back from a given datetime.

    Parameters
    ----------
    dt : date
    airport : str

    Returns
    -------
    history : list of HistoryDay

    """
    baseurl = (
        'http://www.wunderground.com/history/airport/'
        '{airport}/{year}/{month}/{day}/CustomHistory.html')
    params = {
        'dayend': dt.day,
        'monthend': dt.month,
        'yearend': dt.year,
        'format': 1}

    ya = one_year_back(dt)
    url = baseurl.format(
        airport=airport, year=ya.year, month=ya.month, day=ya.day)

    resp = sess.get(url, params=params)
    resp.raise_for_status()

    data = StringIO(resp.text.strip().replace('<br />', ''), newline='')
    data.readline()
    reader = csv.reader(data)

    history = []

    for row in reader:
        dt = datetime.strptime(row[0], '%Y-%m-%d').date()
        precip = float(row[19]) if row[19] != 'T' else 0.0
        events = {s.strip() for s in row[21].split('-')}
        max_temp = float(row[1]) if row[1] else None
        min_temp = float(row[3]) if row[3] else None

        history.append(HistoryDay(
            dt, precip, events, min_temp, max_temp))

    return history


def days_ago(dt):
    """
    Returns how many days ago a given date was.

    """
    return (date.today() - dt).days


def find_rain(history):
    """
    Find the most recent date with rain in a list of rain history.

    History is expected to be in chronological order.

    """
    for day in reversed(history):
        if day.precip > 0 or 'Rain' in day.events:
            return day


def days_since_it_rained(addr):
    """
    Return the number of days since it rained (and some other info)
    for a location.

    Parameters
    ----------
    addr : str

    Returns
    -------
    dsir : int
    day : HistoryDay
    loc : Location
    airport : str

    """
    loc = address_to_geodata(addr)
    airport = get_airport_code(loc.lat, loc.lng)
    dt = date.today()

    for _ in range(5):
        history = history_year(dt, airport)
        rain_day = find_rain(history)

        if rain_day:
            break
        else:
            dt = one_year_back(dt)
    else:
        raise RainError('We went back five years and didn\'t find rain!')

    return days_ago(rain_day.date), rain_day, loc, airport


if __name__ == '__main__':
    import sys
    print(days_since_it_rained(sys.argv[1]))
