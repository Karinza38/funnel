"""Process geonames data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from urllib.parse import urljoin
import csv
import os
import sys
import time
import zipfile

from flask.cli import AppGroup

from progressbar import ProgressBar
from unidecode import unidecode
import progressbar.widgets
import requests

from coaster.utils import getbool

from .. import app
from ..models import (
    GeoAdmin1Code,
    GeoAdmin2Code,
    GeoAltName,
    GeoCountryInfo,
    GeoName,
    db,
)

csv.field_size_limit(sys.maxsize)

geo = AppGroup('geoname', help="Process geoname data.")


@dataclass
class CountryInfoRecord:
    """Geonames country info record."""

    iso_alpha2: str
    iso_alpha3: str
    iso_numeric: str
    fips_code: str
    title: str
    capital: str
    area_in_sqkm: str
    population: str
    continent: str
    tld: str
    currency_code: str
    currency_name: str
    phone: str
    postal_code_format: str
    postal_code_regex: str
    languages: str
    geonameid: str
    neighbours: str
    equivalent_fips_code: str


@dataclass
class GeoNameRecord:
    """Geonames name record."""

    geonameid: str
    title: str
    ascii_title: str
    alternatenames: str
    latitude: str
    longitude: str
    fclass: str
    fcode: str
    country_id: str
    cc2: str
    admin1: str
    admin2: str
    admin3: str
    admin4: str
    population: str
    elevation: str
    dem: str
    timezone: str
    moddate: str


@dataclass
class GeoAdminRecord:
    """Geonames admin record."""

    code: str
    title: str
    ascii_title: str
    geonameid: str


@dataclass
class GeoAltNameRecord:
    """Geonames alt name record."""

    id: str  # noqa: A003
    geonameid: str
    lang: str
    title: str
    is_preferred_name: str
    is_short_name: str
    is_colloquial: str
    is_historic: str


def get_progressbar():
    """Create a progressbar."""
    return ProgressBar(
        widgets=[
            progressbar.widgets.Percentage(),
            ' ',
            progressbar.widgets.Bar(),
            ' ',
            progressbar.widgets.ETA(),
            ' ',
        ]
    )


def downloadfile(basepath: str, filename: str, folder: Optional[str] = None):
    """Download a geoname record file."""
    if not folder:
        folder_file = filename
    else:
        folder_file = os.path.join(folder, filename)
    if (
        os.path.exists(folder_file)
        and (time.time() - os.path.getmtime(folder_file)) < 86400
    ):
        print(f"Skipping re-download of recent {filename}")  # noqa: T201
        return
    print(f"Downloading {filename}...")  # noqa: T201
    url = urljoin(basepath, filename)
    r = requests.get(url, stream=True)
    if r.status_code == 200:
        progress = ProgressBar(
            maxval=int(r.headers.get('content-length', 0)),
            widgets=[
                progressbar.widgets.Percentage(),
                ' ',
                progressbar.widgets.Bar(),
                ' ',
                progressbar.widgets.ETA(),
                ' ',
            ],
        ).start()
        readbytes = 0
        with open(folder_file, 'wb', encoding='utf-8') as fd:
            for chunk in r.iter_content(1024):
                if not chunk:
                    break  # Break when done. The connection remains open for Keep-Alive
                readbytes += len(chunk)
                fd.write(chunk)
                progress.update(readbytes)
        progress.finish()

        if filename.lower().endswith('.zip'):
            with zipfile.ZipFile(folder_file, 'r') as zipf:
                zipf.extractall(folder)


def load_country_info(fd):
    """Load country geonames from the given file descriptor."""
    print("Loading country info...")  # noqa: T201
    progress = get_progressbar()
    countryinfo = [
        CountryInfoRecord(*row)
        for row in csv.reader(fd, delimiter='\t')
        if not row[0].startswith('#')
    ]

    GeoCountryInfo.query.all()  # Load everything into session cache
    for item in progress(countryinfo):
        if item.geonameid:
            ci = GeoCountryInfo.query.get(int(item.geonameid))
            if ci is None:
                ci = GeoCountryInfo(geonameid=int(item.geonameid))
                db.session.add(ci)

            ci.iso_alpha2 = item.iso_alpha2
            ci.iso_alpha3 = item.iso_alpha3
            ci.iso_numeric = int(item.iso_numeric)
            ci.fips_code = item.fips_code
            ci.title = item.title
            ci.capital = item.capital
            ci.area_in_sqkm = Decimal(item.area_in_sqkm) if item.area_in_sqkm else None
            ci.population = int(item.population)
            ci.continent = item.continent
            ci.tld = item.tld
            ci.currency_code = item.currency_code
            ci.currency_name = item.currency_name
            ci.phone = item.phone
            ci.postal_code_format = item.postal_code_format
            ci.postal_code_regex = item.postal_code_regex
            ci.languages = item.languages.split(',')
            ci.neighbours = item.neighbours.split(',')
            ci.equivalent_fips_code = item.equivalent_fips_code

            ci.make_name()

    db.session.commit()


def load_geonames(fd):
    """Load geonames matching fixed criteria from the given file descriptor."""
    progress = get_progressbar()
    print("Loading geonames...")  # noqa: T201
    size = sum(1 for line in fd)
    fd.seek(0)  # Return to start
    loadprogress = ProgressBar(
        maxval=size,
        widgets=[
            progressbar.widgets.Percentage(),
            ' ',
            progressbar.widgets.Bar(),
            ' ',
            progressbar.widgets.ETA(),
            ' ',
        ],
    ).start()

    geonames = []

    # Feature descriptions: http://download.geonames.org/export/dump/featureCodes_en.txt
    # Sorting order, larger number has more weight
    loadfeatures = {
        ('L', 'CONT'): 22,  # Continent
        ('A', 'PCL'): 21,  # Political entity (country)
        ('A', 'PCLD'): 20,  # Dependent political entity
        ('A', 'PCLF'): 19,  # Freely associated state
        ('A', 'PCLI'): 18,  # Independent political entity
        ('A', 'PCLS'): 17,  # Semi-independent political entity
        ('A', 'ADM1'): 16,  # First-order administrative division (state, province)
        ('P', 'PPLC'): 15,  # capital of a political entity
        ('P', 'PPLA'): 14,  # Seat of a first-order admin. division (state capital)
        ('P', 'PPLA2'): 13,  # Seat of a second-order administrative division
        ('P', 'PPLA3'): 12,  # Seat of a third-order administrative division
        ('P', 'PPLA4'): 11,  # Seat of a fourth-order administrative division
        ('P', 'PPLG'): 10,  # Seat of government of a political entity
        ('P', 'PPL'): 9,  # Populated place (city, could be a neighbourhood too)
        ('P', 'PPLR'): 8,  # Religious populated place
        ('P', 'PPLS'): 7,  # Populated places
        ('P', 'PPLX'): 6,  # Section of populated place
        ('S', 'TRIG'): 5,  # Triangulated location (shows up in data instead of P.PPL)
        ('P', 'PPLL'): 4,  # Populated locality
        ('P', 'PPLF'): 3,  # Farm village
        ('A', 'ADM2'): 2,  # Second-order administrative division (district, county)
        ('A', 'ADM3'): 1,  # Third-order administrative division
    }

    for counter, line in enumerate(fd):
        loadprogress.update(counter)
        if not line.startswith('#'):
            rec = GeoNameRecord(*line.strip().split('\t'))
            # Ignore places that have a population below 15,000, but keep places that
            # have a population of 0, since that indicates data wasn't available
            if rec.fclass == 'P' and (
                (
                    rec.population.isdigit()
                    and int(rec.population != 0)
                    and int(rec.population) < 15000
                )
                or not rec.population.isdigit()
            ):
                continue
            if (rec.fclass, rec.fcode) not in loadfeatures:
                continue
            geonames.append(rec)

    loadprogress.finish()

    print(f"Sorting {len(geonames)} records...")  # noqa: T201

    geonames = [
        row[2]
        for row in sorted(
            (
                (
                    loadfeatures[(item.fclass, item.fcode)],
                    int(item.population) if item.population else 0,
                    item,
                )
                for item in geonames
            ),
            reverse=True,
        )
    ]
    GeoName.query.all()  # Load all data into session cache for faster lookup

    print(f"Processing {len(geonames)} records...")  # noqa: T201

    for item in progress(geonames):
        if item.geonameid:
            gn = GeoName.query.get(int(item.geonameid))
            if gn is None:
                gn = GeoName(geonameid=int(item.geonameid))
                db.session.add(gn)

            gn.title = item.title or ''
            gn.ascii_title = item.ascii_title or unidecode(item.title or '').replace(
                '@', 'a'
            )
            gn.latitude = Decimal(item.latitude) or None
            gn.longitude = Decimal(item.longitude) or None
            gn.fclass = item.fclass or None
            gn.fcode = item.fcode or None
            gn.country_id = item.country_id or None
            gn.cc2 = item.cc2 or None
            gn.admin1 = item.admin1 or None
            gn.admin2 = item.admin2 or None
            gn.admin3 = item.admin3 or None
            gn.admin4 = item.admin4 or None
            gn.admin1code = gn.admin1_ref
            gn.admin2code = gn.admin2_ref
            gn.population = int(item.population) if item.population else None
            gn.elevation = int(item.elevation) if item.elevation else None
            gn.dem = int(item.dem) if item.dem else None
            gn.timezone = item.timezone or None
            gn.moddate = (
                datetime.strptime(item.moddate, '%Y-%m-%d').date()
                if item.moddate
                else None
            )

            gn.make_name()
            # Required for future make_name() calls to work correctly
            db.session.flush()

    db.session.commit()


def load_alt_names(fd):
    """Load alternative names for geonames from the given file descriptor."""
    progress = get_progressbar()
    print("Loading alternate names...")  # noqa: T201
    size = sum(1 for line in fd)
    fd.seek(0)  # Return to start
    loadprogress = ProgressBar(
        maxval=size,
        widgets=[
            progressbar.widgets.Percentage(),
            ' ',
            progressbar.widgets.Bar(),
            ' ',
            progressbar.widgets.ETA(),
            ' ',
        ],
    ).start()

    def update_progress(counter):
        """Update the progressbar, converting a statement into an expression."""
        loadprogress.update(counter + 1)
        return True

    geonameids = {r[0] for r in db.session.query(GeoName.id).all()}
    altnames = [
        GeoAltNameRecord(*row)
        for counter, row in enumerate(csv.reader(fd, delimiter='\t'))
        if update_progress(counter)
        and not row[0].startswith('#')
        and int(row[1]) in geonameids
    ]

    loadprogress.finish()

    print(f"Processing {len(altnames)} records...")  # noqa: T201
    GeoAltName.query.all()  # Load all data into session cache for faster lookup

    for item in progress(altnames):
        if item.geonameid:
            rec = GeoAltName.query.get(int(item.id))
            if rec is None:
                rec = GeoAltName(id=int(item.id))
                db.session.add(rec)
            rec.geonameid = int(item.geonameid)
            rec.lang = item.lang or None
            rec.title = item.title
            rec.is_preferred_name = getbool(item.is_preferred_name) or False
            rec.is_short_name = getbool(item.is_short_name) or False
            rec.is_colloquial = getbool(item.is_colloquial) or False
            rec.is_historic = getbool(item.is_historic) or False

    db.session.commit()


def load_admin1_codes(fd):
    """Load admin1 codes from the given file descriptor."""
    print("Loading admin1 codes...")  # noqa: T201
    progress = get_progressbar()
    admincodes = [
        GeoAdminRecord(*row)
        for row in csv.reader(fd, delimiter='\t')
        if not row[0].startswith('#')
    ]

    GeoAdmin1Code.query.all()  # Load all data into session cache for faster lookup
    for item in progress(admincodes):
        if item.geonameid:
            rec = GeoAdmin1Code.query.get(item.geonameid)
            if rec is None:
                rec = GeoAdmin1Code(geonameid=item.geonameid)
                db.session.add(rec)
            rec.title = item.title
            rec.ascii_title = item.ascii_title
            rec.country_id, rec.admin1_code = item.code.split('.')

    db.session.commit()


def load_admin2_codes(fd):
    """Load admin2 codes from the given file descriptor."""
    print("Loading admin2 codes...")  # noqa: T201
    progress = get_progressbar()
    admincodes = [
        GeoAdminRecord(*row)
        for row in csv.reader(fd, delimiter='\t')
        if not row[0].startswith('#')
    ]

    GeoAdmin2Code.query.all()  # Load all data into session cache for faster lookup
    for item in progress(admincodes):
        if item.geonameid:
            rec = GeoAdmin2Code.query.get(item.geonameid)
            if rec is None:
                rec = GeoAdmin2Code(geonameid=int(item.geonameid))
                db.session.add(rec)
            rec.title = item.title
            rec.ascii_title = item.ascii_title
            rec.country_id, rec.admin1_code, rec.admin2_code = item.code.split('.')

    db.session.commit()


@geo.command('download')
def download():
    """Download geoname data."""
    os.makedirs('geoname_data', exist_ok=True)
    for filename in (
        'countryInfo.txt',
        'admin1CodesASCII.txt',
        'admin2Codes.txt',
        'IN.zip',
        'allCountries.zip',
        'alternateNames.zip',
    ):
        downloadfile(
            'http://download.geonames.org/export/dump/', filename, 'geoname_data'
        )


@geo.command('process')
def process():
    """Process downloaded geonames data."""
    with open('geoname_data/countryInfo.txt', newline='', encoding='utf-8') as fd:
        load_country_info(fd)
    with open('geoname_data/admin1CodesASCII.txt', newline='', encoding='utf-8') as fd:
        load_admin1_codes(fd)
    with open('geoname_data/admin2Codes.txt', newline='', encoding='utf-8') as fd:
        load_admin2_codes(fd)
    with open('geoname_data/IN.txt', newline='', encoding='utf-8') as fd:
        load_geonames(fd)
    with open('geoname_data/allCountries.txt', newline='', encoding='utf-8') as fd:
        load_geonames(fd)
    with open('geoname_data/alternateNames.txt', newline='', encoding='utf-8') as fd:
        load_alt_names(fd)


app.cli.add_command(geo)
