"""Bounded downloads from the vehicle marketplaces' known image CDNs."""
import io
import urllib.request
from urllib.parse import urlsplit

IMAGE_HOSTS={'media.carapis.com','ireland.apollo.olxcdn.com','prod.pictures.autoscout24.net',
             'images.marktplaats.com','images.2dehands.com','cdn.gaspedaal.nl',
             'img.classistatic.de','img.kleinanzeigen.de'}
MAX_IMAGE_BYTES=8_000_000

def check_image_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in IMAGE_HOSTS or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Image URL is outside the configured marketplace CDNs')
    return url


def fetch_photo(url):
    check_image_url(url)
    class Redirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,request,fp,code,msg,headers,newurl):
            check_image_url(newurl)
            return super().redirect_request(request,fp,code,msg,headers,newurl)
    opener=urllib.request.build_opener(Redirects())
    request=urllib.request.Request(url,headers={'User-Agent':'TeslaWatcher/2.0','Accept':'image/jpeg,image/webp,image/png'})
    with opener.open(request,timeout=20) as response:
        if not response.headers.get('Content-Type','').lower().startswith('image/'):
            raise ValueError('Expected an image response')
        data=response.read(MAX_IMAGE_BYTES+1)
    if len(data)>MAX_IMAGE_BYTES:raise ValueError('Image exceeds download size limit')
    return jpeg_photo(data)


def jpeg_photo(data):
    from PIL import Image,ImageOps
    with Image.open(io.BytesIO(data)) as source:
        if source.width*source.height>12_000_000:raise ValueError('Image dimensions exceed memory limit')
        image=ImageOps.exif_transpose(source).convert('RGB')
        image.thumbnail((1600,1200))
        output=io.BytesIO();image.save(output,format='JPEG',quality=85)
        return output.getvalue()
