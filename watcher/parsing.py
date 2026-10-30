"""HTML/JSON extraction. Site adapters constrain links; unknown layouts fail closed.

No API requests: embedded JSON was delivered with the website's HTML itself.
"""
from html.parser import HTMLParser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from decimal import Decimal, InvalidOperation
import json
import re
from .models import Listing


class ParseError(RuntimeError):
    pass


@dataclass
class Node:
    tag: str
    attrs: dict
    parent: object = None
    children: list = field(default_factory=list)

    def text(self):
        return ' '.join(c.text() if isinstance(c, Node) else c for c in self.children
                        if not isinstance(c, Node) or c.tag not in ('script', 'style', 'svg'))

    def raw(self):
        return ''.join(c.raw() if isinstance(c, Node) else c for c in self.children)

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()


class Tree(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node('document', {})
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        n = self.current
        while n.parent:
            if n.tag == tag:
                self.current = n.parent
                return
            n = n.parent

    def handle_data(self, text):
        self.current.children.append(text)


def amount(value):
    if isinstance(value, dict):
        value = first(value, 'value', 'price', 'amount', 'priceRaw', 'priceFormatted')
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(value) if value >= 0 else None
    s = re.sub(r'[^0-9,.]', '', str(value))
    if not s:
        return None
    # 54.950,00 / 54,950.00 / 54950.00 / 54.950 / 54 950
    if ',' in s and '.' in s:
        decimal = ',' if s.rfind(',') > s.rfind('.') else '.'
        s = s.replace('.' if decimal == ',' else ',', '').replace(decimal, '.')
    elif re.search(r'[,.]\d{1,2}$', s):
        s = s.replace(',', '.')
    else:
        s = s.replace(',', '').replace('.', '')
    try:
        return round(Decimal(s))
    except InvalidOperation:
        return None


def canonical_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username:
        raise ValueError('Invalid listing URL')
    tracking = {'fbclid', 'gclid', 'msockid', 'ref', 'source', 'source_otp', 'position', 'sort', 'desc',
                'searchId', 'refId', 'action', 's', 'sb', 'od', 'vc'}
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.startswith('utm_') and k not in tracking]
    if p.hostname == 'suchen.mobile.de' and p.path.endswith('/details.html'):
        query = [(k,v) for k,v in query if k=='id']
    fragment = p.fragment if p.hostname.endswith('gaspedaal.nl') and p.fragment.isdigit() else ''
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), fragment))


def first(obj, *keys):
    for k in keys:
        if k in obj and obj[k] not in (None, '', [], {}):
            return obj[k]
    return None


def scalar(x):
    if isinstance(x, dict):
        return first(x, 'name', 'value', 'label', 'text') or ''
    return str(x) if x is not None else ''


def years(value):
    match = re.search(r'(?<!\d)(19\d{2}|20\d{2})(?!\d)', str(value or ''))
    return int(match[1]) if match else None


def from_record(record, source, observed_at):
    """Read common JSON-LD, Next.js and marketplace card fields, without eval."""
    r = dict(record)
    offers = r.get('offers', {})
    if isinstance(offers, dict) and not r.get('url') and offers.get('url'):
        r['url'] = offers['url']
    # AutoScout24's native search card schema, verified from website HTML.
    if isinstance(r.get('vehicle'), dict):
        v = r['vehicle']
        r['title'] = (scalar(r.get('title')) + ' ' + scalar(v.get('modelVersionInput'))).strip()
        r.setdefault('mileage', v.get('mileageInKm'))
        r.setdefault('firstRegistration', r.get('tracking', {}).get('firstRegistration'))
    link = first(r, 'url', 'listing_url', 'vipUrl', 'vip_url', 'detailUrl', 'detail_url', 'href')
    if not isinstance(link, str):
        return None
    url = urljoin(source['url'], link)
    if not re.search(source['link_pattern'], url):
        return None
    title = scalar(first(r, 'title', 'name', 'headline'))
    brand = scalar(first(r, 'brand', 'make', 'brand_name'))
    model = scalar(first(r, 'model', 'model_name'))
    if 'tesla' not in title.lower() and brand.lower() == 'tesla':
        title = f'{brand} {model} {title}'.strip()
    if not title:
        return None
    build = first(r, 'vehicleModelDate', 'productionDate', 'buildYear', 'build_year', 'modelYear', 'year')
    reg = first(r, 'dateVehicleFirstRegistered', 'firstRegistration', 'first_registration')
    year, basis = years(build or reg), ('build_year' if build else 'first_registration' if reg else 'unknown')
    offers = r.get('offers', {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        offers = {}
    price_obj = first(r, 'price', 'price_original', 'priceInfo', 'price_eur')
    price_type = scalar(price_obj.get('priceType')) if isinstance(price_obj, dict) else ''
    raw_price = price_obj if price_obj is not None else offers.get('price')
    price = amount(raw_price)
    # Marktplaats priceInfo.priceCents is explicitly cents; never guess scaling.
    if isinstance(price_obj, dict) and 'priceCents' in price_obj:
        price = round(Decimal(str(price_obj['priceCents'])) / 100)
    currency = scalar(first(r, 'priceCurrency', 'currency', 'price_original_currency') or offers.get('priceCurrency') or 'EUR').upper()
    mileage = amount(first(r, 'mileageFromOdometer', 'mileage', 'mileage_km', 'mileageKm'))
    if isinstance(r.get('mileageFromOdometer'), dict):
        unit = str(r['mileageFromOdometer'].get('unitCode', '')).upper()
        if unit in ('SMI', 'MI', 'MILES'):
            mileage = round(mileage * 1.609344) if mileage is not None else None
    # Marketplace attributes are local to the card, not arbitrary numbers in titles.
    attrs = r.get('attributes', [])
    if isinstance(attrs, list):
        for a in attrs:
            if not isinstance(a, dict):
                continue
            key = scalar(first(a, 'key', 'name', 'label')).lower()
            val = first(a, 'value', 'values')
            if isinstance(val, list):
                val = ' '.join(map(str, val))
            if key in ('constructionyear', 'bouwjaar', 'year', 'buildyear'):
                year, basis = years(val), 'build_year'
            if key in ('mileage', 'mileagekm', 'kilometerstand'):
                mileage = amount(val)
    seller = r.get('seller', r.get('sellerInformation', {}))
    if isinstance(seller, dict):
        seller = first(seller, 'name', 'companyName', 'sellerName') or ''
    desc = scalar(r.get('description'))
    flags = (title + ' ' + desc + ' ' + price_type).casefold()
    # Unknown card years may be recovered only from explicitly labelled text.
    if year is None:
        m = re.search(r'(?:bouwjaar|bj\.?|baujahr|modeljaar)\s*[:\s]*((?:19|20)\d{2})', title + ' ' + desc, re.I)
        if m:
            year, basis = int(m[1]), 'build_year'
    location = r.get('location', '')
    if isinstance(location, dict):
        location = first(location, 'cityName', 'city', 'name') or ''
    country = source.get('country', '')
    if isinstance(r.get('location'), dict):
        country = r['location'].get('countryCode', country)
    return Listing(source=source['name'], source_id=str(first(r, 'listing_id', 'itemId', 'listingId', 'id') or canonical_url(url)),
                   url=canonical_url(url), title=' '.join(title.split()), year=year, year_basis=basis,
                   price=price, currency=currency, mileage=mileage, country=country,
                   seller=scalar(seller), vin=scalar(first(r, 'vehicleIdentificationNumber', 'vin')),
                   plate=scalar(first(r, 'licensePlate', 'plate', 'vehicle_no')), location=scalar(location),
                   published_at=scalar(first(r, 'datePosted', 'published_at', 'first_seen_at')),
                   observed_at=observed_at,
                   is_wanted=bool(re.search(r'\b(gezocht|gesuch|gesucht|suche|wanted)\b', flags)),
                   is_lease=bool(re.search(r'per maand|/\s*(?:mnd|month|monat)|monthly|lease only|leaseprijs', flags)),
                   damaged=bool(re.search(r'\b(schadeauto|unfallwagen|unfallfahrzeug|bastlerfahrzeug|accident[eé])\b', flags)
                                or re.search(r'\b(unfall|schade|beschadigd)\b', title, re.I)))


def record_from_card(node, anchor, source):
    text = ' '.join(node.text().split())
    if len(text) > 6000:
        return None
    headings = [n.text() for n in node.walk() if n.tag in ('h2', 'h3')]
    title = next((t for t in headings if re.search(r'model[\s-]*s\b', t, re.I)), anchor.text().strip())
    if not re.search(r'model[\s-]*s\b', title, re.I):
        # A photo link may be empty; inspect the local heading/image only.
        headings = [n.text() for n in node.walk() if n.tag in ('h2', 'h3')]
        title = next((t for t in headings if re.search(r'model[\s-]*s\b', t, re.I)), '')
    if not title:
        return None
    if 'tesla' not in title.lower() and 'tesla' in text.lower():
        title = 'Tesla ' + title
    r = {'url': anchor.attrs['href'], 'title': title, 'description': text}
    # Prefer semantic markup over prose (battery replacements also mention years).
    for n in node.walk():
        prop = n.attrs.get('itemprop', '')
        value = n.attrs.get('content') or n.text().strip()
        if prop in ('price', 'priceCurrency', 'vehicleModelDate', 'mileageFromOdometer', 'dateVehicleFirstRegistered'):
            r[prop] = value
        for attr, key in [('data-year', 'year'), ('data-price', 'price'), ('data-mileage', 'mileage'), ('data-id', 'id')]:
            if n.attrs.get(attr):
                r.setdefault(key, n.attrs[attr])
    if not r.get('price'):
        # German sites use a trailing euro sign. A prefix search there can
        # accidentally capture the mileage following that sign instead.
        pattern = r'([\d][\d.,]*)\s*€' if source.get('country')=='DE' else r'€\s*([\d][\d.,]*)'
        m = re.search(pattern, text)
        if m:
            r['price'] = m[1].strip(' .,')
        else:
            m = re.search(r'([\d][\d.,]*)\s*€', text)
            if m:
                r['price'] = m[1]
    m = re.search(r'([\d][\d. ,]*)\s*km\b', text, re.I)
    if m and not r.get('mileageFromOdometer'):
        r['mileage'] = m[1]
    # Site card year selectors (never take an arbitrary 4-digit title number).
    year_re = source.get('year_pattern')
    m = re.search(year_re, text, re.I) if year_re else None
    if m:
        r['year' if source.get('year_basis', 'build_year') == 'build_year' else 'firstRegistration'] = m[1]
    return r


def parse_page(html, source, observed_at):
    head = html[:20000].lower()
    for marker in ('<title>access denied', '<title>just a moment', 'verify you are human', 'cf-chl-', '<title>captcha'):
        if marker in head:
            raise ParseError('Block/captcha page, no listing result')
    tree = Tree(html)
    listings = []
    nodes = list(tree.root.walk())
    def visit(obj):
        if isinstance(obj, dict):
            item = from_record(obj, source, observed_at)
            if item:
                listings.append(item)
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            for value in obj:
                visit(value)
    for n in nodes:
        if n.tag == 'script' and (n.attrs.get('type') in ('application/ld+json', 'application/json') or n.attrs.get('id') == '__NEXT_DATA__'):
            try:
                visit(json.loads(n.raw()))
            except (json.JSONDecodeError, RecursionError):
                continue
    for n in nodes:
        if n.tag != 'a' or not n.attrs.get('href'):
            continue
        url = urljoin(source['url'], n.attrs['href'])
        if not re.search(source['link_pattern'], url):
            continue
        p = n
        for _ in range(7):
            cls = str(p.attrs.get('class', '')) + ' ' + str(p.attrs.get('data-testid', ''))
            if p.tag in ('article', 'li') or re.search(source.get('card_pattern', r'(?!)'), cls, re.I):
                r = record_from_card(p, n, source)
                if r:
                    item = from_record(r, source, observed_at)
                    if item:
                        listings.append(item)
                break
            if not p.parent:
                break
            p = p.parent
    native = native_extract(nodes, source, observed_at)
    if native is not None:
        # Prefer the source's own inventory array; avoid recommendations and SEO examples.
        return native
    # Same card often appears in both embedded JSON and DOM. Keep richest record.
    merged = {}
    for item in listings:
        old = merged.get(item.url)
        score = sum(v not in ('', None) for v in (item.year, item.price, item.mileage, item.vin, item.plate))
        old_score = -1 if old is None else sum(v not in ('', None) for v in (old.year, old.price, old.mileage, old.vin, old.plate))
        if score > old_score:
            merged[item.url] = item
    next_url = None
    for n in nodes:
        if n.tag not in ('a', 'link') or not n.attrs.get('href'):
            continue
        label = (n.attrs.get('aria-label', '') + ' ' + n.text()).lower().strip()
        if n.attrs.get('rel') == 'next' or re.fullmatch(r'(next|volgende|weiter|suivant)( page| pagina| seite)?[ »›→]*', label):
            next_url = urljoin(source['url'], n.attrs['href'])
            break
    kind=source.get('kind')
    if kind=='mobile':
        if any(n.tag=='button' and n.attrs.get('data-testid')=='pagination:next' and 'disabled' not in n.attrs for n in nodes):
            current=source.get('current_url',source['url'])
            page=int(dict(parse_qsl(urlsplit(current).query)).get('pageNumber',1))
            next_url=set_query(current,pageNumber=page+1)
    if kind=='kleinanzeigen':
        next_anchor=next((n for n in nodes if n.tag=='a' and n.attrs.get('aria-label')=='Nächste' and n.attrs.get('href')),None)
        if next_anchor:
            next_url=urljoin(source['url'],next_anchor.attrs['href'])
    empty = any(re.search(p, html, re.I) for p in source.get('empty_patterns', []))
    if kind=='mobile' and not merged:
        totals=[d['numResultsTotal'] for o in flight_objects(nodes) for d in dictionaries(o) if 'numResultsTotal' in d]
        if totals and all(t==0 for t in totals):
            empty=True
    if not merged and not empty:
        raise ParseError('No recognised listing cards or explicit zero-results marker; layout may have changed')
    return list(merged.values()), next_url, empty


def set_query(url, **values):
    p = urlsplit(url)
    query = dict(parse_qsl(p.query))
    query.update({k:str(v) for k,v in values.items()})
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(query),''))


def native_extract(nodes, source, observed_at):
    kind = source.get('kind', source['name'])
    current_url = source.get('current_url', source['url'])
    for n in nodes:
        if n.tag != 'script' or n.attrs.get('id') != '__NEXT_DATA__':
            continue
        try:
            data = json.loads(n.raw())['props']['pageProps']
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if kind == 'marketplace' and 'searchRequestAndResponse' in data:
            data = data['searchRequestAndResponse']
            if data.get('hasErrors'):
                raise ParseError('Marketplace returned search errors')
            raw = data.get('listings', [])
            if not isinstance(raw, list):
                raise ParseError('Marketplace inventory is not a list')
            listings = [x for r in raw if (x := from_record(r, source, observed_at))]
            total = int(data.get('totalResultCount', 0))
            req = data.get('searchRequest', {})
            pagination = req.get('pagination', {})
            size = int(pagination.get('limit',30))
            page = int(pagination.get('offset',0)) // size + 1
            # Native pagination paths preserve the filter path.
            base = re.sub(r'/p/\d+/?$', '/', source['url'].split('?')[0]).rstrip('/')
            next_url = f'{base}/p/{page+1}/' if page * size < total else None
            if total > 0 and not listings:
                raise ParseError('Marketplace reports inventory but no cards could be parsed')
            return listings, next_url, total == 0
        if kind == 'autoscout' and 'listings' in data:
            raw = data['listings']
            listings = [x for r in raw if (x := from_record(r,source,observed_at))]
            page = int(dict(parse_qsl(urlsplit(current_url).query)).get('page',1))
            pages = int(data.get('numberOfPages',1))
            total = int(data.get('numberOfResults',0))
            if total > 0 and not listings:
                raise ParseError('AutoScout24 reports inventory but no cards could be parsed')
            return listings, set_query(current_url,page=page+1) if page < pages else None, total == 0
    if kind == 'carapis':
        cards = [n for n in nodes if n.tag=='a' and 'vehicle-card' in n.attrs.get('class','').split()]
        if not cards:
            return None
        listings = []
        countries = {'Netherlands':'NL','Belgium':'BE','Germany':'DE','Sweden':'SE','Norway':'NO','Denmark':'DK',
                     'France':'FR','Italy':'IT','Austria':'AT','Poland':'PL','United Kingdom':'GB'}
        for card in cards:
            def field(cls):
                return next((x.text().strip() for x in card.walk() if cls in x.attrs.get('class','').split()),'')
            title = field('vehicle-card-title')
            subtitle = field('vehicle-card-subtitle')
            text = card.text()
            r = {'url':card.attrs['href'],'title':title+' '+subtitle}
            y = re.search(r'\b(20\d{2})\b',subtitle)
            r['year'] = int(y[1]) if y else None
            p = re.search(r'([$€£])\s*([\d,.]+)',text)
            r['price'] = p[2] if p else None
            r['currency'] = {'$':'USD','€':'EUR','£':'GBP'}.get(p[1] if p else '', 'UNKNOWN')
            m = re.search(r'([\d, .]+)\s*km',field('vehicle-card-specs'))
            r['mileage'] = m[1] if m else None
            x = from_record(r,source,observed_at)
            if x:
                meta = field('vehicle-card-meta')
                x.country = next((v for k,v in countries.items() if meta.startswith(k)), '')
                x.year_basis = 'advertised_year'
                listings.append(x)
        # The site's page links may discard filters. Reapply every search parameter.
        page = int(dict(parse_qsl(urlsplit(current_url).query)).get('page',1))
        links = [urljoin(current_url,n.attrs.get('href','')) for n in nodes if n.tag=='a' and n.attrs.get('href')]
        has_next = any(dict(parse_qsl(urlsplit(u).query)).get('page') == str(page+1) for u in links)
        return listings, set_query(current_url,page=page+1) if has_next else None, False
    if kind == 'gaspedaal':
        for obj in flight_objects(nodes):
            for data in dictionaries(obj):
                if 'occasions' not in data or 'numberOfPages' not in data:
                    continue
                listings = []
                for r in data['occasions']:
                    a=r.get('autogegevens',{}); general=a.get('algemeen',{}); history=a.get('geschiedenis',{})
                    portals=r.get('portalen',[])
                    seller=r.get('aanbieder',{}).get('aanbiedergegevens',{})
                    record={'id':r.get('advertentieId'),'url': portals[0]['klikUrl'] if portals else '',
                            'title':' '.join(str(general.get(k,'')) for k in ('merknaam','modelnaam','uitvoering')),
                            'year':history.get('bouwjaar'),'mileage':history.get('kilometerstand'),
                            'price':r.get('prijs',{}).get('totaalInclusiefBtw'), 'published_at':r.get('datumGeplaatst'),
                            'location':seller.get('plaatsnaam'),'seller':seller.get('naamsvermelding')}
                    x=from_record(record,source,observed_at)
                    if x:
                        listings.append(x)
                page=int(dict(parse_qsl(urlsplit(current_url).query)).get('page',1))
                return listings,set_query(current_url,page=page+1) if page<int(data['numberOfPages']) else None, not data['occasions']
        for n in nodes:
            if n.tag!='script' or n.attrs.get('type')!='application/ld+json':
                continue
            try:
                data=json.loads(n.raw())
            except json.JSONDecodeError:
                continue
            if not isinstance(data,dict) or data.get('@type')!='ItemList' or 'numberOfItems' not in data:
                continue
            listings=[]
            for item in data.get('itemListElement',[]):
                r=dict(item.get('item',{}))
                if re.search(r'#\d+$',r.get('@id','')):
                    r['url']=r['@id']
                    r['id']=r['@id'].split('#')[-1]
                x=from_record(r,source,observed_at)
                if x:
                    listings.append(x)
            total=int(data.get('numberOfItems',0))
            page=int(dict(parse_qsl(urlsplit(current_url).query)).get('page',1))
            page_size=source.get('page_size',24)
            return listings,set_query(current_url,page=page+1) if page*page_size<total else None,total==0
    return None


def dictionaries(obj):
    if isinstance(obj,dict):
        yield obj
        for value in obj.values():
            yield from dictionaries(value)
    elif isinstance(obj,list):
        for value in obj:
            yield from dictionaries(value)


def flight_objects(nodes):
    """Decode JSON records embedded in React Flight HTML; never execute JavaScript."""
    chunks=[]
    decoder=json.JSONDecoder()
    for n in nodes:
        if n.tag!='script':
            continue
        raw=n.raw()
        for m in re.finditer(r'self\.__next_f\.push\(', raw):
            try:
                frame,_=decoder.raw_decode(raw[m.end():])
                if isinstance(frame,list) and len(frame)>1 and frame[0]==1 and isinstance(frame[1],str):
                    chunks.append(frame[1])
            except json.JSONDecodeError:
                continue
    stream=''.join(chunks)
    for match in re.finditer(r'\b[0-9a-f]+:(?=[\[{])',stream):
        try:
            value,_=decoder.raw_decode(stream[match.end():])
            yield value
        except json.JSONDecodeError:
            continue
