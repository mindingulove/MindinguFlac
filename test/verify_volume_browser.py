import functools, json, math, threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
script = (root/'static/app.js').read_text()
graph = script[script.index('let _audioCtx = null;'):script.index('function browserOutputLatencySeconds()')]
fixture = ('<audio id="audioPlayer"></audio><script>const state = {settings:{normalize_volume:true}};'
           'const $=id=>document.getElementById(id);' + graph + '</script>').encode()
class Handler(SimpleHTTPRequestHandler):
 def do_GET(self):
  if self.path == '/fixture':
   self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers();self.wfile.write(fixture)
  else: super().do_GET()
 def log_message(self,*args): pass
server = ThreadingHTTPServer(('127.0.0.1',0), functools.partial(Handler,directory=str(root/'static')))
threading.Thread(target=server.serve_forever, daemon=True).start()
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required'])
 page=browser.new_page()
 page.goto(f'http://127.0.0.1:{server.server_port}/fixture')
 result=page.evaluate('''async () => {
   // Use actual HTMLMediaElement decoded PCM to check its volume placement in
   // the graph, worklet loading, and insertion into the existing audio clock.
   const audio = $("audioPlayer");
   const wav = amplitude => {
     const n=48000*5, bytes=new ArrayBuffer(44+n*2), v=new DataView(bytes);
     const text=(pos,s)=>{for(let i=0;i<s.length;i++) v.setUint8(pos+i,s.charCodeAt(i));};
     text(0,"RIFF");v.setUint32(4,36+n*2,true);text(8,"WAVE");text(12,"fmt ");
     v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);
     v.setUint32(24,48000,true);v.setUint32(28,96000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);
     text(36,"data");v.setUint32(40,n*2,true);
     for(let i=0;i<n;i++) v.setInt16(44+i*2,Math.round(32767*amplitude*Math.sin(2*Math.PI*440*i/48000)),true);
     return URL.createObjectURL(new Blob([bytes],{type:"audio/wav"}));
   };
   // blob URLs share this origin.
   audio.src=wav(0.05);
   await updateBrowserNormalization();
   if (!_normalizationNode) throw Error("worklet did not attach");
   const analyzer=_audioCtx.createAnalyser(); analyzer.fftSize=4096;
   const mute=_audioCtx.createGain();mute.gain.value=0;
   _normalizationNode.disconnect();_normalizationNode.connect(analyzer);analyzer.connect(mute);mute.connect(_audioCtx.destination);
   const sleep=ms=>new Promise(r=>setTimeout(r,ms));
   const read=()=>{const a=new Float32Array(analyzer.fftSize);analyzer.getFloatTimeDomainData(a);return Math.sqrt(a.reduce((s,x)=>s+x*x,0)/a.length);};
   const results=[];
   for(const [amplitude, volume, enabled] of [[0.05,1,true],[0.7,1,true],[0.7,0.25,true],[0.7,0.25,false]]) {
     audio.pause();audio.src=wav(amplitude);audio.volume=volume;
     state.settings.normalize_volume=enabled;
     await updateBrowserNormalization();
     _normalizationNode.port.postMessage({reset:true,volume});
     await audio.play();await sleep(3000);
     results.push({amplitude,volume,enabled,rms:read(),position:audio.currentTime});
   }
   audio.pause();await _audioCtx.close();return results;
 }''')
 print(json.dumps(result,indent=2))
 assert all(r['position']>2 for r in result), 'audio clock did not advance'
 assert abs(20*math.log10(result[0]['rms']/result[1]['rms']))<0.4
 assert abs(result[2]['rms']/result[1]['rms']-.25)<.01
 assert abs(result[3]['rms']-.7*.25/math.sqrt(2))<.005
 browser.close()
server.shutdown();server.server_close()
print('Real Chromium media playback: matching, slider, bypass and advancing clock passed.')
