import csv
import logging
import os
import re
from collections import namedtuple
from datetime import date, datetime, timedelta
from io import StringIO

import requests
from lxml import html

from dsirexceptions import (
    ZeroResultsError, GeocodeError, AirportError, RainError)

logger = logging.getLogger('dsir')


Location = namedtuple('Location', ('address', 'lat', 'lng'))
HistoryDay = namedtuple(
    'HistoryDay', ('date', 'precip', 'events', 'min_temp', 'max_temp'))

sess = requests.Session()
sess.headers.update(
    {'user-agent': 'www.dayssinceitrained.com/jiffyclub@gmail.com'})


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


def parse_precip_history(history_page):
    doc = html.document_fromstring(history_page)
    history_table = doc.get_element_by_id('obsTable')

    history = []
    table_rows = history_table.iterchildren()

    while True:
        try:
            row = next(table_rows)
        except StopIteration:
            break

        if row.tag == 'thead':
            # this row contains a year we need to capture
            # it's in the first element
            current_year = row[0][0].text.strip()

            # next row will be another header that contains the
            # current month in the first column
            row = next(table_rows)
            current_month = row[0][0].text.strip()
        else:
            # row contains data
            cols = list(row.find('tr'))

            current_day = cols[0].text_content().strip().zfill(2)
            dt = datetime.strptime(
                f'{current_year}-{current_month}-{current_day}', '%Y-%b-%d').date()
            precip = (
                float(cols[19].text_content().strip())
                if cols[19].text_content().strip() not in ('', '-', 'T') else 0.0)
            events = {s.strip().lower() for s in cols[20].text_content().split(',')}
            max_temp = (
                float(cols[1].text_content().strip())
                if cols[1].text_content().strip() not in ('', '-') else None)
            min_temp = (
                float(cols[3].text_content().strip())
                if cols[3].text_content().strip() not in ('', '-') else None)

            history.append(HistoryDay(
                dt, precip, events, min_temp, max_temp))

    return history


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
    }

    ya = one_year_back(dt)
    url = baseurl.format(
        airport=airport, year=ya.year, month=ya.month, day=ya.day)

    resp = sess.get(url, params=params)
    resp.raise_for_status()
    logger.debug('history retrieved for date: {} and airport: {}'.format(
        dt, airport))
    logger.debug(
        'building history array for date: {} and airport: {}'.format(
            dt, airport))

    history = parse_precip_history(resp.content)

    logger.debug(
        'returning history array for date: {} and airport: {}'.format(
            dt, airport))
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

    Returns
    -------
    rain_day : HistoryDay

    """
    for day in reversed(history):
        if day.precip > more_than:
            return day


def find_rain_event(history):
    """
    Find the most recent date with a recorded rain event, ignoring precip.

    History is expected to be in chronological order.

    Parameters
    ----------
    history : list of HistoryDay
    more_than : float, optional
        Looks for days on which more than this much rain was recorded.

    Returns
    -------
    rain_day : HistoryDay

    """
    precip_events = {'rain', 'snow'}
    for day in reversed(history):
        if precip_events.intersection(day.events):
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

    all_history = []

    for _ in range(5):
        history = history_year(dt, airport)
        all_history = history + all_history
        rain_day = find_rain(history, more_than=more_than)

        if rain_day:
            break
        else:
            dt = one_year_back(dt)
    else:
        rain_day = find_rain_event(all_history)
        if not rain_day:
            raise RainError('We went back five years and didn\'t find rain!')

    logger.debug(
        ('found {precip} inches of rain on {date} '
         'for address {addr!r} and airport {airport}').format(
            precip=rain_day.precip, date=rain_day.date, addr=loc.address,
            airport=airport))
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


def wu_year_history_url(airport, dt):
    """
    Get the URL for year history on WU.

    """
    logger.debug(
        'building WU year history URL for date: {} and airport: {}'.format(
            dt, airport))
    ya = one_year_back(dt)
    return (
        'http://www.wunderground.com/history/airport'
        '/{airport}/{yearstart}/{monthstart}/{daystart}/CustomHistory.html?'
        'dayend={day}&monthend={month}&yearend={yearend}').format(
            airport=airport.upper(), yearstart=ya.year, yearend=dt.year,
            monthstart=ya.month, month=dt.month, day=dt.day, daystart=ya.day)


if __name__ == '__main__':
    import sys
    print(days_since_it_rained(sys.argv[1], float(sys.argv[2])))
