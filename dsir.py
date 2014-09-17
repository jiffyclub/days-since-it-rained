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

logger = logging.getLogger('dsir')


Location = namedtuple('Location', ('address', 'lat', 'lng'))

sess = requests.Session()
sess.headers.update(
    {'user-agent': 'dayssinceitrained.com/jiffyclub@gmail.com'})


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
    logger.debug(
        'looking up airport code for lat/lng: {}, {}'.format(lat, lng))
    baseurl = (
        'http://www.wunderground.com/cgi-bin/findweather/getForecast'
        '?query={},{}').format(lat, lng)
    resp = sess.get(baseurl)
    resp.raise_for_status()

    code = re.search(r'/history/airport/([a-zA-Z]{4})/', resp.text)

    if not code:
        msg = 'Could not find airport code for lat/lng: {}, {}'.format(
            lat, lng)
        logger.error(msg)
        raise AirportError(msg)

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
    logger.debug(
        'requesting history for date: {} and airport: {}'.format(dt, airport))
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
    data.readline()  # burn the header row
    reader = csv.reader(data)

    history = []

    for row in reader:
        dt = datetime.strptime(row[0], '%Y-%m-%d').date()
        precip = float(row[19]) if row[19] != 'T' else 0.0
        events = {s.strip().lower() for s in row[21].split('-')}
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


def find_rain(history, more_than=0):
    """
    Find the most recent date with rain in a list of rain history.

    History is expected to be in chronological order.

    Parameters
    ----------
    history : list of HistoryDay
    more_than : float, optional
        Looks for days on which more than this much rain was recorded.

    """
    for day in reversed(history):
        if day.precip > more_than:
            return day


def days_since_it_rained(address, more_than=0):
    """
    Return the number of days since it rained (and some other info)
    for a location.

    Parameters
    ----------
    address : str
    more_than : float, optional
        Looks for days on which more than this much rain was recorded.

    Returns
    -------
    dsir : int
    day : HistoryDay
    loc : Location
    airport : str

    """
    logger.debug(
        'looking for more than {} rain for address: {!r}'.format(
            more_than, address))
    loc = address_to_geodata(address)
    airport = get_airport_code(loc.lat, loc.lng)
    dt = date.today()

    for _ in range(5):
        history = history_year(dt, airport)
        rain_day = find_rain(history, more_than=more_than)

        if rain_day:
            break
        else:
            dt = one_year_back(dt)
    else:
        raise RainError('We went back five years and didn\'t find rain!')

    return days_ago(rain_day.date), rain_day, loc, airport


def daily_history_url(airport, dt):
    """
    Get the URL for the daily history page at WU for an airport and date.

    """
    logger.debug(
        'building daily history url for date: {} and airport: {}'.format(
            dt, airport))
    return (
        'http://www.wunderground.com/history/airport'
        '/{airport}/{year}/{month}/{day}/DailyHistory.html').format(
            airport=airport.upper(), year=dt.year, month=dt.month, day=dt.day)


if __name__ == '__main__':
    import sys
    print(days_since_it_rained(sys.argv[1], float(sys.argv[2])))
