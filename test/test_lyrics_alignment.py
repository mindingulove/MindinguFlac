import ast
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import lyrics_alignment as align
import db

LINES = ["Bright rivers flow beyond the hills", "Morning birds awaken in the valley",
         "Heavy clouds gather over distant mountains", "Quiet footsteps follow along the shore",
         "Autumn leaves whisper beneath our window", "Silver stars appear above the garden"]
LYRICS = '\n'.join(f'[{(15+i*13)//60:02d}:{(15+i*13)%60:02d}.00]{text}' for i,text in enumerate(LINES))


def observed(offset=0, noise=False):
    words = []
    for i, line in enumerate(LINES):
        for j, word in enumerate(align._normalized(line)):
            words.append({'text': word, 'start':15+i*13+j*.35+offset+(0.15 if i%2 else -.15), 'confidence': .95})
        if noise: words.append({'text':'nonsense','start':20+i*13,'confidence':.1})
    return words


class AlignmentTests(unittest.TestCase):
    def test_multiple_independent_phrases_find_positive_and_negative_offsets(self):
        for offset in (7.5,-12.2,0):
            result = align.align_words(LYRICS, observed(offset,noise=True))
            self.assertTrue(result['matched'],result)
            self.assertAlmostEqual(result['offset'],offset,delta=.16)
            self.assertEqual(result['anchors'],6)

    def test_full_phrase_agreement_tolerates_uncertain_word_recognition(self):
        words=observed(2)
        for i,word in enumerate(words):
            if i%7==0: word['confidence']=.12
        result=align.align_words(LYRICS,words)
        self.assertTrue(result['matched'],result)
        self.assertAlmostEqual(result['offset'],2,delta=.16)

    def test_does_not_retime_from_a_single_phrase_or_low_confidence_hallucinations(self):
        self.assertFalse(align.align_words(LYRICS,observed()[:12])['matched'])
        self.assertFalse(align.align_words(LYRICS,[{**w,'confidence':.2} for w in observed()])['matched'])
        self.assertFalse(align.align_words(LYRICS,[{'text':'different song','start':20,'confidence':1}]*50)['matched'])

    def test_repeated_chorus_cannot_choose_an_arbitrary_repetition(self):
        repeated = '\n'.join(f'[00:{i*10:02d}]Bright rivers flow beyond the hills' for i in range(6))
        words = []
        for i in range(6):
            words += [{'text':w,'start':i*10+j*.2,'confidence':.95} for j,w in enumerate(align._normalized(LINES[0]))]
        self.assertFalse(align.align_words(repeated,words)['matched'])

    def test_lrc_offset_and_enhanced_word_timestamps(self):
        parsed=align.parse_lines('[offset:500]\n[00:10.00]<00:10.00>Bright <00:11.00>rivers flow')
        self.assertEqual(parsed[0]['time'],9.5)
        self.assertEqual(parsed[0]['words'],['bright','rivers','flow'])
        self.assertEqual(align.parse_lines('<00:12.10>Bright <00:12.40>rivers flow')[0]['time'],12.1)

    def test_android_native_bridge_receives_float_pcm_and_uses_the_same_matcher(self):
        calls=[]
        class Bridge:
            @staticmethod
            def transcribeNative(path,pcm):
                calls.append((path,len(pcm)))
                return bytearray(json.dumps({'words':observed(4)}).encode())
        with patch.dict('os.environ',{'MINDINGUFLAC_ANDROID':'1'}), \
             patch.dict(sys.modules,{'java':SimpleNamespace(jclass=lambda name:Bridge)}), \
             patch.object(align,'model_path',return_value=Path('/model.bin')):
            words=align.recognize(np.zeros(16000,dtype=np.float32))
        self.assertEqual(calls,[('/model.bin',64000)])
        self.assertTrue(align.align_words(LYRICS,words)['matched'])


class LyricsAlignmentCacheTests(unittest.TestCase):
    def test_manual_nudges_and_auto_results_stay_per_recording_and_lyric_version(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(db,'_DB_PATH',Path(tmp)/'test.db'), patch.object(db,'_local',threading.local()), \
             patch.object(db,'_run_one_time_migrations',lambda conn:None):
            db.nudge_lyrics_audio_alignment('original',.25)
            db.save_lyrics_audio_alignment('original',{'status':'matched','offset':12})
            db.nudge_lyrics_audio_alignment('original',.25)
            self.assertEqual(db.get_lyrics_audio_alignment('original')['manual_offset'],.5)
            self.assertEqual(db.get_lyrics_audio_alignment('original')['result']['offset'],12)
            self.assertEqual(db.get_lyrics_audio_alignment('edit'),{'result':None,'manual_offset':0})

class AlignmentApiTests(unittest.TestCase):
    def test_growing_stream_retries_and_final_result_is_cached_per_audio_and_text(self):
        import time
        from unittest.mock import Mock
        tree=ast.parse(Path('app.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'_align_lyrics','_lyrics_alignment_key'}]
        store={}
        fake_db=SimpleNamespace(get_lyrics_audio_alignment=lambda key:{'result':store.get(key),'manual_offset':.25},
                               save_lyrics_audio_alignment=lambda key,result:store.__setitem__(key,result))
        ns={'hashlib':hashlib,'threading':threading,'db':fake_db,'_lyrics_alignment_lock':threading.Lock(),
            '_lyrics_alignment_slot':threading.BoundedSemaphore(1),'_lyrics_alignment_jobs':{},
            '_video_sync_audio_key':lambda body:body.get('stream_url','local'),
            '_monochrome_stream_url':lambda url:url,
            '_video_sync_audio_path':lambda body:Path('buffer.audio')}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'app.py','exec'),ns)
        body={'lyrics':LYRICS,'stream_url':'actual-source'}
        done=threading.Event()
        def partial(*args):
            done.set();return {'matched':False,'pending':True,'audio_seconds':20}
        with patch.object(align,'available',return_value=True),patch.object(align,'compute_alignment',side_effect=partial):
            self.assertEqual(ns['_align_lyrics'](body)['status'],'checking')
            self.assertTrue(done.wait(1))
            for _ in range(100):
                if ns['_lyrics_alignment_slot'].acquire(blocking=False):
                    ns['_lyrics_alignment_slot'].release();break
                time.sleep(.001)
            self.assertFalse(store)
        def complete(*args): return {'matched':True,'offset':7.5,'audio_seconds':120}
        with patch.object(align,'available',return_value=True),patch.object(align,'compute_alignment',side_effect=complete) as compute:
            ns['_align_lyrics'](body)
            for _ in range(100):
                if store: break
                time.sleep(.001)
            result=ns['_align_lyrics'](body)
            self.assertEqual(result['status'],'matched')
            self.assertEqual(result['offset'],7.5)
            self.assertEqual(result['manual_offset'],.25)
            self.assertEqual(compute.call_count,1)
        self.assertNotEqual(ns['_lyrics_alignment_key'](body),ns['_lyrics_alignment_key']({**body,'stream_url':'another-recording'}))
        self.assertNotEqual(ns['_lyrics_alignment_key'](body),ns['_lyrics_alignment_key']({**body,'lyrics':LYRICS+' different'}))
