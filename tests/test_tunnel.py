import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from watcher.tunnel import QuickTunnel

class TunnelTests(unittest.TestCase):
    def test_vendor_digest_and_cached_binary(self):
        binary=b'fake binary for test only'
        asset={'name':'cloudflared-linux-amd64','digest':'sha256:'+hashlib.sha256(binary).hexdigest(),'browser_download_url':'https://github.com/cloudflare/cloudflared/releases/download/test/cloudflared-linux-amd64'}
        with tempfile.TemporaryDirectory() as directory:
            tunnel=QuickTunnel(directory,8080)
            with patch('urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps({'tag_name':'test','assets':[asset]}).encode()),io.BytesIO(binary)]) as get:
                target=tunnel.binary();self.assertEqual(target.read_bytes(),binary)
                self.assertEqual(tunnel.binary(),target);self.assertEqual(get.call_count,2)
            self.assertEqual(target.stat().st_mode&0o777,0o700)
    def test_missing_digest_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            payload={'tag_name':'test','assets':[{'name':'cloudflared-linux-amd64'}]}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ValueError):QuickTunnel(directory,8080).binary()
    def test_checksum_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            payload={'tag_name':'test','assets':[{'name':'cloudflared-linux-amd64','digest':'sha256:'+'0'*64,'browser_download_url':'https://github.com/cloudflare/cloudflared/releases/download/test/client'}]}
            with patch('urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps(payload).encode()),io.BytesIO(b'incorrect')]):
                with self.assertRaises(ValueError):QuickTunnel(directory,8080).binary()
            self.assertFalse((Path(directory)/'bin'/'cloudflared').exists())
