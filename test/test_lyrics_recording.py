import ast
import asyncio
from pathlib import Path
import re
import unittest
from unittest.mock import patch


class TimedLyricsTests(unittest.TestCase):
    def test_plain_priority_answer_does_not_hide_timed_lyrics(self):
        tree = ast.parse(Path('app.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in {'_fetch_timed_lyrics', '_lyrics_is_synced'}]
        ns = {'asyncio': asyncio, 're': re}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), ns)
        calls = []
        async def fetch(**kwargs):
            calls.append(kwargs)
            provider = kwargs['providers'][0]
            if provider == 'spotify': return ('Plain text', provider)
            if provider == 'lrclib': return ('[00:15.63]Timed line', provider)
            return ('', '')
        with patch('local_metadata.lyrics.fetch_lyrics_async', side_effect=fetch):
            text, provider = asyncio.run(ns['_fetch_timed_lyrics']({'title':'Song','artist':'Artist','isrc':'actual','duration_s':239}))
        self.assertEqual(provider, 'lrclib')
        self.assertTrue(ns['_lyrics_is_synced'](text))
        self.assertTrue(all(c['isrc'] == 'actual' and c['duration_s'] == 239 for c in calls))
        async def plain(**kwargs): return ('Plain text', kwargs['providers'][0])
        with patch('local_metadata.lyrics.fetch_lyrics_async', side_effect=plain):
            self.assertEqual(asyncio.run(ns['_fetch_timed_lyrics']({'title':'Song'})), ('Plain text','spotify'))
