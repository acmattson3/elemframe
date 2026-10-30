import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from runtime_control import stop_instance


class ShutdownSafety(unittest.TestCase):
    def test_missing_runtime_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('runtime_control.urllib.request.urlopen') as request:
                stop_instance(Path(root));request.assert_not_called()

    def test_external_runtime_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root);state=data/'.runtime.json'
            state.write_text(json.dumps({'url':'https://example.invalid','token':'test'}))
            with patch('runtime_control.urllib.request.urlopen') as request:
                with self.assertRaisesRegex(RuntimeError,'Invalid local'):stop_instance(data)
                request.assert_not_called()
            self.assertTrue(state.exists())

    def test_other_application_is_not_stopped(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root);state=data/'.runtime.json'
            state.write_text(json.dumps({'url':'http://127.0.0.1:12345','token':'test'}))
            with patch('runtime_control.urllib.request.urlopen',return_value=io.BytesIO(json.dumps({'app':'Other','data_dir':root}).encode())) as request:
                with self.assertRaisesRegex(RuntimeError,'another application'):stop_instance(data)
                self.assertEqual(request.call_count,1)
            self.assertTrue(state.exists())

    def test_refused_stale_server_is_not_force_killed(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root);state=data/'.runtime.json'
            state.write_text(json.dumps({'url':'http://127.0.0.1:12345','token':'test','pid':1}))
            with patch('runtime_control.urllib.request.urlopen',side_effect=urllib.error.URLError(ConnectionRefusedError(111,'refused'))):
                stop_instance(data)
            self.assertFalse(state.exists())


if __name__=='__main__':unittest.main()
