from pathlib import Path
import shutil,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]))
import worker

class ProductPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'built.app';self.app=self.root/'approved.app'
        for app,data in [(self.source,b'new signed product'),(self.app,b'old signed product')]:
            app.mkdir();(app/'binary').write_bytes(data)
        self.backup=self.app.with_name(self.app.name+'.cache-previous')
    def test_complete_copy_replaces_output_without_changing_compiler_product(self):
        worker.publish_product(self.source,self.app)
        self.assertEqual((self.app/'binary').read_bytes(),b'new signed product')
        self.assertEqual((self.source/'binary').read_bytes(),b'new signed product')
        self.assertFalse(self.backup.exists())
    def test_failed_copy_preserves_previous_signed_output(self):
        with patch.object(worker,'clone',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):worker.publish_product(self.source,self.app)
        self.assertEqual((self.app/'binary').read_bytes(),b'old signed product')
    def test_restart_restores_product_after_power_cut_between_renames(self):
        self.app.rename(self.backup)
        worker.recover_product(self.app)
        self.assertEqual((self.app/'binary').read_bytes(),b'old signed product')
        self.assertFalse(self.backup.exists())
    def test_restart_keeps_completed_replacement_and_cleans_old_copy(self):
        self.app.rename(self.backup);shutil.copytree(self.source,self.app)
        worker.recover_product(self.app)
        self.assertEqual((self.app/'binary').read_bytes(),b'new signed product')
        self.assertFalse(self.backup.exists())
