"""Fetching website HTML only: urllib first, optional Playwright rendering."""
import json
import gzip
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from pathlib import Path
from datetime import datetime
from .parsing import parse_page, ParseError,set_query

MAX_BYTES = 8_000_000


class Fetcher:
    def __init__(self, mode='auto', headed=False):
        self.mode = mode
        self.headed = headed
        self.playwright = self.browser = None

    def close(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def http(self, url, source):
        allowed = source.get('allowed_hosts', [urlsplit(source['url']).hostname])
        class Redirects(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if urlsplit(newurl).hostname not in allowed:
                    raise ParseError('Redirect to unconfigured host')
                return super().redirect_request(req,fp,code,msg,headers,newurl)
        opener = urllib.request.build_opener(Redirects())
        request = urllib.request.Request(url,headers={
            'User-Agent':source.get('user_agent','Mozilla/5.0 (compatible; TeslaWatcher/1.0; personal vehicle search)'),
            'Accept':'text/html,application/xhtml+xml', 'Accept-Language':'nl-NL,nl;q=0.9,de;q=0.8,en;q=0.7'})
        for attempt in range(3):
            try:
                with opener.open(request,timeout=source.get('timeout',35)) as response:
                    content_type = response.headers.get('Content-Type','')
                    if 'html' not in content_type:
                        raise ParseError('Expected HTML, got '+content_type)
                    data=response.read(MAX_BYTES+1)
                    if len(data)>MAX_BYTES:
                        raise ParseError('HTML exceeds size limit')
                    return data.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
            except urllib.error.HTTPError as exc:
                if exc.code not in (429,500,502,503,504) or attempt==2:
                    raise
                # Respect Retry-After seconds, within a bounded scan deadline.
                delay=exc.headers.get('Retry-After','')
                seconds=int(delay) if delay.isdigit() else 2**(attempt+1)
                if seconds>60:
                    raise ParseError('Source asks for a longer pause; retry next scan') from exc
                time.sleep(seconds)
        raise ParseError('Fetch retries exhausted')

    def render(self,url,source):
        if self.browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise ParseError('Browser required: install requirements-browser.txt and run playwright install chromium') from exc
            self.playwright=sync_playwright().start()
            self.browser=self.playwright.chromium.launch(headless=not self.headed)
        page=self.browser.new_page(locale=source.get('locale','nl-NL'))
        try:
            page.route('**/*',lambda route: route.abort() if route.request.resource_type in ('image','media','font') else route.continue_())
            response=page.goto(url,wait_until='domcontentloaded',timeout=source.get('timeout',35)*1000)
            if response and response.status>=400:
                raise ParseError(f'Browser HTTP {response.status}')
            page.wait_for_timeout(source.get('render_wait_ms',3500))
            html=page.content()
            if len(html.encode())>MAX_BYTES:
                raise ParseError('Rendered HTML exceeds size limit')
            return html
        finally:
            page.close()

    def page(self,url,source,timestamp):
        if self.mode=='browser':
            html=self.render(url,source)
            return parse_page(html,{**source,'current_url':url},timestamp),html
        try:
            html=self.http(url,source)
        except urllib.error.HTTPError as exc:
            if self.mode!='auto' or exc.code!=403:
                raise
            # A normal browser attempt, without stealth plugins or CAPTCHA solving.
            html=self.render(url,source)
            return parse_page(html,{**source,'current_url':url},timestamp),html
        try:
            return parse_page(html,{**source,'current_url':url},timestamp),html
        except ParseError:
            # No CAPTCHA bypass. Browser fallback only for unrecognised JS layouts.
            if self.mode!='auto' or any(x in html.lower() for x in ('verify you are human','cf-chl-','<title>captcha')):
                raise
            html=self.render(url,source)
            return parse_page(html,{**source,'current_url':url},timestamp),html


def scan_source(fetcher,source,timestamp,archive_dir=None,capture_html=False):
    if source.get('partition_by_registration_year'):
        # Smaller ordinary search queries reduce deep-page dependence. All year
        # partitions must succeed before the source baseline is advanced.
        merged={};total_pages=0;began=time.monotonic()
        for year in range(source.get('min_registration_year',2022),datetime.now().year+2):
            remaining=source.get('max_duration_seconds',480)-(time.monotonic()-began)
            if remaining<=0:raise ParseError('Year-partition scan exceeded time budget')
            partition={**source,'partition_by_registration_year':False,
                       'url':set_query(source['url'],fr=f'{year}:{year}'),'max_duration_seconds':remaining}
            capture=Path(archive_dir)/str(year) if archive_dir else None
            items,pages=scan_source(fetcher,partition,timestamp,capture,capture_html)
            total_pages+=pages
            merged.update({x.url:x for x in items})
        return list(merged.values()),total_pages
    url=source['url']
    allowed=source.get('allowed_hosts',[urlsplit(url).hostname])
    visited=set(); listings={}; pages=0
    started=time.monotonic()
    while url:
        if time.monotonic()-started>source.get('max_duration_seconds',480):
            raise ParseError('Source scan exceeded time budget; inventory incomplete')
        if url in visited:
            raise ParseError('Pagination loop; incomplete inventory')
        if pages>=source.get('max_pages',50):
            raise ParseError('Page limit reached; incomplete inventory. Increase max_pages or narrow website filters.')
        if urlsplit(url).scheme!='https' or urlsplit(url).hostname not in allowed:
            raise ParseError('Pagination left the configured website')
        visited.add(url)
        (items,next_url,empty),html=fetcher.page(url,source,timestamp)
        pages+=1
        print(json.dumps({'source':source['name'],'page':pages,'parsed_on_page':len(items)},ensure_ascii=False),flush=True)
        if capture_html and archive_dir:
            folder=Path(archive_dir)/'html'/timestamp.replace(':','-')
            folder.mkdir(parents=True,exist_ok=True)
            (folder/f'{source["name"]}-{pages}.html').write_text(html)
        before=len(listings)
        for x in items:
            listings[x.url]=x
        if pages>1 and items and len(listings)==before:
            raise ParseError('Pagination returned only repeated cards; incomplete inventory')
        url=next_url
        if url:
            time.sleep(source.get('request_delay',2))
    return list(listings.values()),pages


def archive_snapshot(folder,source,timestamp,listings=None,error=None,pages=0,compress=False):
    path=Path(folder)/timestamp[:10]
    path.mkdir(parents=True,exist_ok=True)
    payload={'timestamp':timestamp,'source':source,'status':'error' if error else 'ok',
             'error':str(error) if error else None,'pages':pages,
             'listings':[x.to_dict() for x in listings or []]}
    target=path/(timestamp.replace(':','-')+'-'+source+'.json')
    if compress:
        target=target.with_suffix('.json.gz')
        with gzip.open(target,'wt',encoding='utf-8') as handle:json.dump(payload,handle,ensure_ascii=False)
    else:target.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return payload
