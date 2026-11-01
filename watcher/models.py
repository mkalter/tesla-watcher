from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str
    year: int | None = None
    year_basis: str = 'unknown'
    price: int | None = None
    currency: str = 'EUR'
    mileage: int | None = None
    country: str = ''
    seller: str = ''
    vin: str = ''
    plate: str = ''
    location: str = ''
    published_at: str = ''
    observed_at: str = ''
    is_wanted: bool = False
    is_lease: bool = False
    damaged: bool = False
    image_url: str = ''

    def to_dict(self):
        return asdict(self)


def reject_reason(x, filters):
    title = x.title.casefold()
    # These marketplace links are already inside the Tesla car category;
    # sellers do not always repeat the brand in their title.
    url = urlsplit(x.url)
    tesla_category = (
        (x.source, url.hostname) in {
            ('marktplaats', 'www.marktplaats.nl'),
            ('2dehands', 'www.2dehands.be'),
        }
        and url.path.startswith('/v/auto-s/tesla/')
    )
    if not (re.search(r'\btesla\b', title) or tesla_category) or not re.search(r'\bmodel[\s-]*s\b', title):
        return 'not_model_s'
    if x.is_wanted:
        return 'wanted_ad'
    if x.is_lease:
        return 'lease_or_monthly_price'
    if x.damaged and not filters.get('include_damaged', False):
        return 'damaged'
    if x.year is None:
        return 'unknown_year'
    if not filters.get('allow_first_registration', True) and x.year_basis != 'build_year':
        return 'build_year_unconfirmed'
    if x.year < filters.get('min_year', 2022):
        return 'too_old'
    if x.year > datetime.now().year + 1:
        return 'invalid_year'
    if filters.get('countries') and x.country not in filters['countries']:
        return 'country_not_selected'
    if filters.get('exclude_plaid', False) and re.search(r'\bplaid\b', title):
        return 'plaid'
    variant = filters.get('variant', 'any')
    if variant == 'long_range' and not re.search(r'long[\s-]*range|\blr\b', title):
        return 'long_range_unconfirmed'
    if x.currency != 'EUR' and filters.get('max_price') is not None:
        return 'non_eur_price'
    if filters.get('max_price') is not None:
        if x.price is None or x.price > filters['max_price']:
            return 'price_missing_or_high'
    if filters.get('max_mileage') is not None:
        if x.mileage is None or x.mileage > filters['max_mileage']:
            return 'mileage_missing_or_high'
    return ''


def message(x, kind='new', previous_price=None):
    clean=lambda value:' '.join(re.sub(r'[*_~`]', '',str(value)).split())[:90]
    money=lambda value:(('€' if x.currency=='EUR' else clean(x.currency))+' '+f'{value:,}'.replace(',','.')) if value is not None else 'Prijs op aanvraag'
    variant='Plaid' if re.search(r'\bplaid\b',x.title,re.I) else 'Long Range' if re.search(r'long[ -]*range|\blr\b',x.title,re.I) else ''
    title='Tesla Model S'+(' '+variant if variant else '')
    countries={'NL':'Nederland','BE':'België','DE':'Duitsland','SE':'Zweden','NO':'Noorwegen','DK':'Denemarken','FR':'Frankrijk','US':'Verenigde Staten'}
    location=' · '.join(v for v in [clean(x.location),countries.get(x.country,clean(x.country))] if v) or 'Niet vermeld'
    sources={'carapis':'CarAPIS','autoscout_nl':'AutoScout24 NL','autoscout_be':'AutoScout24 BE','autoscout_de':'AutoScout24 DE','marktplaats':'Marktplaats','gaspedaal':'Gaspedaal','mobile':'mobile.de','2dehands':'2dehands.be','kleinanzeigen':'Kleinanzeigen'}
    year=str(x.year) if x.year else 'Niet vermeld'
    if x.year_basis=='first_registration':year+=' (eerste toelating)'
    mileage=f'{x.mileage:,}'.replace(',','.')+' km' if x.mileage is not None else 'Niet vermeld'
    lines=[f'*{title}*',f'*{money(x.price)}*','',f'Jaar: {year}',f'Kilometerstand: {mileage}',f'Locatie: {location}',f'Bron: {sources.get(x.source,clean(x.source))}']
    if previous_price is not None:lines+=['',f'Prijs verlaagd: {money(previous_price)} → {money(x.price)}']
    lines+=['','Bekijk advertentie:',x.url]
    if kind=='example':lines+=['','_Voorbeeldbericht · geen nieuwe advertentie_']
    return '\n'.join(lines)
