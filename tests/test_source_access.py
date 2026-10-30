import io
import unittest
import urllib.error
from unittest.mock import patch
from watcher.sources import Fetcher, SourceAccessError, forbidden_reason

class SourceAccessTests(unittest.TestCase):
    def error(self, body):
        return urllib.error.HTTPError('https://suchen.mobile.de/fahrzeuge/search.html',403,'Forbidden',{},io.BytesIO(body))
    def test_identifies_datadome_without_disclosing_challenge(self):
        error = self.error(b'<script src="https://geo.captcha-delivery.com/captcha/?secret=private"></script>')
        reason = forbidden_reason(error)
        self.assertIn('DataDome', reason)
        self.assertNotIn('private', reason)
        self.assertNotIn('https://', reason)
    def test_unknown_forbidden_is_not_called_bot_detection(self):
        self.assertIn('did not provide a recognised reason', forbidden_reason(self.error(b'Forbidden')))
    def test_refused_http_does_not_trigger_browser_or_retries(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=self.error(b'DataDome')), patch.object(Fetcher,'render') as render:
            with self.assertRaisesRegex(SourceAccessError,'DataDome'):
                Fetcher('auto').page('https://suchen.mobile.de/fahrzeuge/search.html', {'url':'https://suchen.mobile.de/fahrzeuge/search.html'}, '2026-10-30T14:00:00Z')
            render.assert_not_called()
