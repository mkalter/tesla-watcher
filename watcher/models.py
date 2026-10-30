from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re


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

    def to_dict(self):
        return asdict(self)


def reject_reason(x, filters):
    title = x.title.casefold()
    if not re.search(r'\btesla\b', title) or not re.search(r'\bmodel[\s-]*s\b', title):
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
    euro = lambda v: (('€' if x.currency=='EUR' else x.currency) + ' ' + f'{v:,}'.replace(',', '.')) if v is not None else 'prijs onbekend'
    km = f'{x.mileage:,}'.replace(',', '.') + ' km' if x.mileage is not None else 'km onbekend'
    label = 'Nieuwe Tesla Model S' if kind == 'new' else 'Prijsdaling Tesla Model S'
    lines = [label, x.title, f'{x.year} ({x.year_basis}) · {euro(x.price)} · {km}',
             f'{x.country} · {x.source}']
    if previous_price is not None:
        lines.append(f'Was {euro(previous_price)}')
    if x.location:
        lines.append(x.location)
    lines.extend([x.url, f'Gezien: {x.observed_at}'])
    return '\n'.join(lines)
