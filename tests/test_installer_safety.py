import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import linux_install


@unittest.skipUnless(os.name=='posix','Linux installer transaction checks')
class InstallerSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='elemframe-install-safety-')
        self.root=Path(self.tmp.name);self.source=self.root/'payload';self.source.mkdir()
        (self.source/'ElemFrame').write_text('old executable')
        (self.source/'portable.txt').write_text('portable')
        self.target=self.root/'installed app';self.data=self.root/'media'
        self.env=patch.dict(os.environ,{'HOME':str(self.root/'home'),
            'XDG_CONFIG_HOME':str(self.root/'config'),'XDG_DATA_HOME':str(self.root/'share')})
        self.env.start()
        self.args=argparse.Namespace(install_dir=str(self.target),data_dir=str(self.data),
            startup=True,kiosk=True,desktop=False,yes=True,launch=False)

    def tearDown(self):self.env.stop();self.tmp.cleanup()

    def test_unrelated_directory_is_not_overwritten(self):
        self.target.mkdir();sentinel=self.target/'personal.txt';sentinel.write_text('keep')
        with self.assertRaisesRegex(RuntimeError,'unrelated'):
            linux_install.install(self.source,self.args)
        self.assertEqual(sentinel.read_text(),'keep')

    def test_data_cannot_be_inside_program_directory(self):
        self.args.data_dir=str(self.target/'photos')
        with self.assertRaisesRegex(RuntimeError,'separate'):
            linux_install.install(self.source,self.args)
        self.assertFalse(self.target.exists())

    def test_failed_upgrade_rolls_back_program_and_shortcuts(self):
        linux_install.install(self.source,self.args)
        state=json.loads((self.target/'install-state.json').read_text())
        snapshots={Path(p):Path(p).read_text() for p in state['entries']}
        self.data.mkdir();(self.data/'keep.txt').write_text('keep')
        (self.source/'ElemFrame').write_text('new executable')
        self.args.startup=False
        real=linux_install.atomic_text
        fail=[True]
        def interrupted(path,*args,**kwargs):
            if path.suffix=='.desktop' and fail[0]:
                fail[0]=False;raise OSError('simulated desktop write failure')
            return real(path,*args,**kwargs)
        with patch.object(linux_install,'atomic_text',side_effect=interrupted):
            with self.assertRaisesRegex(OSError,'simulated'):
                linux_install.install(self.source,self.args)
        self.assertEqual((self.target/'ElemFrame').read_text(),'old executable')
        self.assertEqual((self.data/'keep.txt').read_text(),'keep')
        for path,text in snapshots.items():self.assertEqual(path.read_text(),text)

    def test_uninstall_keeps_media_and_user_modified_shortcut(self):
        linux_install.install(self.source,self.args)
        self.data.mkdir();(self.data/'keep.txt').write_text('keep')
        startup=self.root/'config/autostart/org.elemframe.ElemFrame.desktop'
        startup.write_text('[Desktop Entry]\nName=Another application\n')
        linux_install.uninstall(self.target,self.args)
        self.assertFalse(self.target.exists())
        self.assertEqual((self.data/'keep.txt').read_text(),'keep')
        self.assertTrue(startup.exists())


if __name__=='__main__':unittest.main()
