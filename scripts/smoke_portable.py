"""Exercise the extracted release, not the checkout or its installed modules."""
import argparse
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--raw-sample',type=Path);args=parser.parse_args()
    folder=args.folder.resolve()
    windows=(folder/'runtime/python.exe').exists()
    cli=[str(folder/'runtime/python.exe'),str(folder/'app/launcher.py')] if windows else [str(folder/'ElemFrame')]
    native=[str(folder/'ElemFrame.exe')] if windows else cli
    env=os.environ.copy();env['ELEMFRAME_HOME']=str(folder)
    for name in ['PYTHONPATH','ELEMFRAME_DATA_DIR','ELEMFRAME_CONFIG','PICTURE_LIBRARY','PICTURE_REMOVABLE_ROOTS']:
        env.pop(name,None)
    subprocess.run([*cli,'--self-test'],env=env,check=True,timeout=60)
    with tempfile.TemporaryDirectory(prefix='ElemFrame package check ') as temporary:
        root=Path(temporary);data=root/'data';usb=root/'USB card';usb.mkdir()
        from PIL import Image
        Image.new('RGB',(96,64),(50,130,180)).save(usb/'Camera photo.tiff')
        if args.raw_sample:
            shutil.copy2(args.raw_sample,usb/('Camera RAW'+args.raw_sample.suffix))
        env['PICTURE_REMOVABLE_ROOTS']=str(usb)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        def request(path,body=None,token=None):
            headers={'Content-Type':'application/json'}
            if token:headers['X-ElemFrame-Token']=token
            req=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            with urllib.request.urlopen(req,timeout=30) as response:
                return response.status,response.headers,response.read()
        process=subprocess.Popen([*native,'--no-browser','--data-dir',str(data),'--port',str(port)],cwd=root,env=env)
        try:
            for _ in range(150):
                if process.poll() is not None:raise RuntimeError('Packaged launcher exited before startup')
                try:
                    health=json.loads(request('/api/health')[2]);break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('Packaged server startup timed out')
            assert health['app']=='ElemFrame' and Path(health['data_dir'])==data
            assert b'Manage media' in request('/')[2]
            assert b'function startSlideshow' in request('/app.js')[2]
            assert json.loads(request('/api/list?side=removable')[2])['items'][0]['name']=='USB card'
            response=request('/api/copy',{'source_side':'removable','source_paths':['0/Camera photo.tiff'],'target_side':'local','target_path':''})
            assert not json.loads(response[2])['issues']
            prepared=json.loads(request('/api/prepare',{'path':'Camera photo.tiff'})[2])
            image=request(prepared['url']);assert image[1]['Content-Type']=='image/jpeg' and image[2][:2]==b'\xff\xd8'
            if args.raw_sample:
                path='Camera RAW'+args.raw_sample.suffix
                imported=json.loads(request('/api/copy',{'source_side':'removable','source_paths':['0/'+path],'target_side':'local','target_path':''})[2])
                assert not imported['issues']
                prepared=json.loads(request('/api/prepare',{'path':path})[2])
                raw_image=request(prepared['url']);assert raw_image[1]['Content-Type']=='image/jpeg' and raw_image[2][:2]==b'\xff\xd8'
                print('PASS actual camera RAW conversion in packaged runtime',flush=True)
            request('/api/config',{'display_time':7.5,'volume':.4,'shuffle':True})
            assert json.loads((data/'config.json').read_text())['display_time']==7.5
            # A second process must attach to the existing instance and exit cleanly.
            subprocess.run([*native,'--no-browser','--data-dir',str(data),'--port',str(port)],env=env,check=True,timeout=15)
            try:request('/api/shutdown',{},'wrong-token');raise AssertionError('Unprotected shutdown')
            except urllib.error.HTTPError as error:assert error.code==403
            subprocess.run([*cli,'--stop','--data-dir',str(data)],env=env,check=True,timeout=15)
            assert process.wait(timeout=15)==0
            assert not (data/'.runtime.json').exists()
            print(json.dumps({'package':str(folder),'platform':os.name,'assets':'ok','portable_paths':'ok',
                              'drive_fixture':'ok','legacy_import':'ok','settings':'ok','single_instance':'ok','shutdown':'ok'}),flush=True)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)


if __name__=='__main__':main()
