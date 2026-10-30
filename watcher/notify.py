import json
import os
import time
import urllib.request
import urllib.error


def deliver(store, config, opener=None, clock=None):
    """Durable outbox. Unknown send outcomes go to manual review, never blind retry."""
    clock = time.time() if clock is None else clock
    opener = opener or urllib.request.urlopen
    token = os.environ.get('BRIDGE_TOKEN', '')
    if not token:
        raise ValueError('BRIDGE_TOKEN is missing')
    count = 0
    for event in store.pending(clock):
        request = urllib.request.Request(config['bridge_url'].rstrip('/') + '/send',
            data=json.dumps({'event_id':event['id'], 'text':event['text']}).encode(),
            headers={'Authorization':'Bearer ' + token, 'Content-Type':'application/json'}, method='POST')
        try:
            with opener(request, timeout=90) as response:
                body = json.loads(response.read())
                if body.get('state') != 'sent':
                    raise ValueError('Unconfirmed send result')
            store.set_event(event['id'], 'sent')
            count += 1
        except urllib.error.HTTPError as exc:
            if exc.code in (401,403,429,503):
                # Bridge promises these failures occur BEFORE sending.
                delay = min(3600, 30 * 2 ** min(event['attempts'], 7))
                store.set_event(event['id'], 'queued', f'bridge HTTP {exc.code}', clock+delay)
            else:
                store.set_event(event['id'], 'uncertain', f'bridge HTTP {exc.code}; review before retry')
        except Exception as exc:
            # A network timeout may happen after WhatsApp accepted the message.
            store.set_event(event['id'], 'uncertain', type(exc).__name__ + '; review before retry')
    return count
