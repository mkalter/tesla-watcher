"""Regression checks against reduced structures captured on 30 October 2026."""
import unittest,json
from pathlib import Path
from watcher.parsing import parse_page
ROOT=Path(__file__).resolve().parents[1]
class CapturedFixtureTests(unittest.TestCase):
 def test_captured_source_records(self):
  config=json.loads((ROOT/'config.json').read_text())
  sources={s['name']:s for s in config['sources']}
  metadata=json.loads((ROOT/'fixtures/metadata.json').read_text())
  for row in metadata:
   with self.subTest(source=row['source']):
    xs,_,_=parse_page((ROOT/row['fixture']).read_text(),sources[row['source']],'2026-10-30T09:00:00+00:00')
    self.assertEqual(len(xs),1)
    for field,value in row['expected'].items():self.assertEqual(getattr(xs[0],field),value,field)
