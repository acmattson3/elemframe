"""Exercise real pointer/touch interaction over playing videos in Chromium/Edge.

Needs websocket-client only in the test environment, not in the product bundle.
Uses an isolated browser profile, data directory, and silent generated clips.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def wait_for(function, timeout=20):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            result=function()
            if result:return result
        except (OSError, ConnectionError):pass
        time.sleep(.05)
    raise AssertionError('Timed out waiting for browser state')


class CDP:
    def __init__(self,url):
        import websocket
        self.socket=websocket.create_connection(url,timeout=10,suppress_origin=True)
        self.number=0

    def call(self,method,params=None):
        self.number+=1
        self.socket.send(json.dumps({'id':self.number,'method':method,'params':params or {}}))
        while True:
            response=json.loads(self.socket.recv())
            if response.get('id')==self.number:
                if 'error' in response:raise AssertionError(response['error'])
                return response.get('result',{})

    def evaluate(self,expression):
        result=self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in result:raise AssertionError(result['exceptionDetails'])
        return result['result'].get('value')

    def rect(self,selector):
        return self.evaluate(f"(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x,y:r.y,width:r.width,height:r.height}}}})()")

    def click(self,selector, touch=False):
        rect=self.rect(selector);x=rect['x']+rect['width']/2;y=rect['y']+rect['height']/2
        if touch:
            self.call('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
            self.call('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else:
            self.call('Input.dispatchMouseEvent',{'type':'mousePressed','x':x,'y':y,'button':'left','clickCount':1})
            self.call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x,'y':y,'button':'left','clickCount':1})

    def screenshot(self,path):
        path.write_bytes(base64.b64decode(self.call('Page.captureScreenshot',{'format':'png','fromSurface':True})['data']))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package',type=Path);parser.add_argument('--dev-modules',type=Path)
    parser.add_argument('--screenshots',type=Path,default=Path(tempfile.gettempdir())/'elemframe-overlay-screenshots')
    args=parser.parse_args()
    if args.dev_modules:sys.path.insert(0,str(args.dev_modules.resolve()))
    root=Path(__file__).resolve().parents[1]
    if (root/'media.py').exists():sys.path.insert(0,str(root))
    if args.package and (args.package/'app').is_dir():sys.path.insert(0,str(args.package.resolve()/'app'))
    import media
    args.screenshots=args.screenshots.resolve();args.screenshots.mkdir(parents=True,exist_ok=True)
    if args.package:
        package=args.package.resolve();windows=(package/'runtime/python.exe').exists()
        native=[str(package/('ElemFrame.exe' if windows else 'ElemFrame'))]
    else:
        package=root;native=[sys.executable,str(root/'launcher.py')]
    env=os.environ.copy();env['ELEMFRAME_HOME']=str(package)
    for key in ['ELEMFRAME_CONFIG','PICTURE_LIBRARY','ELEMFRAME_DATA_DIR','PICTURE_REMOVABLE_ROOTS']:env.pop(key,None)
    with tempfile.TemporaryDirectory(prefix='ElemFrame overlay regression ') as temporary:
        temporary=Path(temporary);data=temporary/'data';library=data/'library';library.mkdir(parents=True)
        (data/'config.json').write_text(json.dumps({'display_time':3,'transition_time':1,'shuffle':False,'volume':0}))
        for name,filter in [('01-first.mp4','testsrc2=size=640x360:rate=20'),('02-second.mp4','color=c=0x285a7a:size=640x360:rate=20')]:
            subprocess.run([media.ffmpeg(),'-nostdin','-v','error','-y','-f','lavfi','-i',filter,
                            '-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000',
                            '-t','8','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',
                            str(library/name)],check=True,timeout=30,
                           **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
        port=unused_port();debug_port=unused_port();url=f'http://127.0.0.1:{port}'
        # Match a desktop launch without inheriting redirected PowerShell pipes.
        app=subprocess.Popen([*native,'--no-browser','--data-dir',str(data),'--port',str(port)],env=env,
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        browser=None;connection=None
        try:
            wait_for(lambda:urllib.request.urlopen(url+'/api/health',timeout=1).status==200)
            candidates=[]
            if os.name=='nt':
                for key in ['PROGRAMFILES(X86)','PROGRAMFILES']:
                    if env.get(key):candidates.append(Path(env[key])/'Microsoft/Edge/Application/msedge.exe')
            for name in ['chromium','chromium-browser','google-chrome','msedge']:
                found=shutil.which(name)
                if found:candidates.append(Path(found))
            executable=next((p for p in candidates if p.exists()),None)
            if executable is None:raise RuntimeError('Chromium or Microsoft Edge is required for this browser regression check')
            browser=subprocess.Popen([str(executable),'--headless','--no-first-run','--no-default-browser-check',
                '--autoplay-policy=no-user-gesture-required','--window-size=1280,720',
                f'--remote-debugging-port={debug_port}','--remote-debugging-address=127.0.0.1',
                '--user-data-dir='+str(temporary/'browser-profile'),'about:blank'],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            debug=f'http://127.0.0.1:{debug_port}'
            wait_for(lambda:urllib.request.urlopen(debug+'/json/version',timeout=1).status==200)
            target=json.load(urllib.request.urlopen(urllib.request.Request(debug+'/json/new?'+url,method='PUT')))
            connection=CDP(target['webSocketDebuggerUrl'])
            connection.call('Runtime.enable');connection.call('Page.enable')
            connection.call('Emulation.setDeviceMetricsOverride',{'width':1280,'height':720,'deviceScaleFactor':1,'mobile':False})
            wait_for(lambda:connection.evaluate("!!document.querySelector('#play') && !document.querySelector('#play').disabled"))
            connection.click('#play')
            wait_for(lambda:connection.evaluate("(()=>{const v=document.querySelector('#slideStage video');return v && !v.paused && v.currentTime>.2})()"))
            def check_hud():
                assert connection.evaluate("(()=>{const b=document.querySelector('#volumeButton'),r=b.getBoundingClientRect(),top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return b.checkVisibility() && !!top.closest('#volumeControl') && document.querySelector('#slideFilename').checkVisibility() && document.querySelector('#slideFilename').textContent.length>0})()")
            check_hud();connection.click('#volumeButton')
            wait_for(lambda:connection.evaluate("document.querySelector('#volumeButton').getAttribute('aria-expanded')==='true'"))
            wait_for(lambda:connection.rect('#volumeSliderWrap')['height']>150)
            slider=connection.rect('#volumeSlider');x=slider['x']+slider['width']/2;y=slider['y']+5
            connection.call('Input.dispatchMouseEvent',{'type':'mousePressed','x':x,'y':y,'button':'left','clickCount':1})
            connection.call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x,'y':y,'button':'left','clickCount':1})
            assert connection.evaluate("document.querySelector('#slideStage video').volume>.8 && !document.querySelector('#slideStage video').muted")
            connection.screenshot(args.screenshots/'video-controls.png')
            print('PASS filename and volume remain visible/hit-testable while video plays; real pointer input changes video volume',flush=True)
            wait_for(lambda:connection.evaluate("document.querySelector('#volumeButton').getAttribute('aria-expanded')==='false'"),7)
            check_hud()
            wait_for(lambda:connection.evaluate("(()=>{const layers=document.querySelectorAll('#slideStage video');if(layers.length!==2)return false;const opacity=Number(getComputedStyle(layers[1]).opacity);return opacity>.1 && opacity<.8})()"),8)
            check_hud();connection.click('#volumeButton')
            wait_for(lambda:connection.evaluate("document.querySelector('#volumeButton').getAttribute('aria-expanded')==='true'"))
            assert connection.evaluate("document.querySelector('#slideshow').classList.contains('active')")
            wait_for(lambda:connection.rect('#volumeSliderWrap')['height']>150)
            connection.screenshot(args.screenshots/'crossfade-controls.png')
            print('PASS filename and volume remain above both video layers during crossfade',flush=True)
            wait_for(lambda:connection.evaluate("document.querySelector('#slideFilename').textContent==='02-second' && document.querySelectorAll('#slideStage video').length===1"))
            check_hud();connection.click('#volumeButton')
            connection.call('Emulation.setTouchEmulationEnabled',{'enabled':True,'maxTouchPoints':1})
            connection.click('#volumeButton',touch=True)
            wait_for(lambda:connection.evaluate("document.querySelector('#volumeButton').getAttribute('aria-expanded')==='true'"))
            assert connection.evaluate("document.querySelector('#slideshow').classList.contains('active')")
            print('PASS touch tap opens volume during Windows/Chromium video playback without exiting slideshow',flush=True)
        finally:
            if connection:
                try:connection.call('Browser.close')
                except Exception:pass
                try:connection.socket.close()
                except Exception:pass
            if browser:
                try:browser.wait(timeout=10)
                except subprocess.TimeoutExpired:browser.terminate();browser.wait(timeout=10)
            state_path=data/'.runtime.json'
            if state_path.exists():
                state=json.loads(state_path.read_text())
                request=urllib.request.Request(state['url']+'/api/shutdown',data=b'{}',
                    headers={'X-ElemFrame-Token':state['token'],'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=5):pass
            assert app.wait(timeout=60)==0
            wait_for(lambda:not state_path.exists())
            print('PASS isolated browser and application shut down cleanly',flush=True)


if __name__=='__main__':main()
