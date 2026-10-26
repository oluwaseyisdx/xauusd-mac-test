import tempfile
import unittest
from pathlib import Path
from read_bridge import parse_snapshot, find_snapshot, sanitized_report, FILENAME

HEADER="run_id;seq;terminal_connected;demo_account;quotes_available;symbol;bid;ask;tick_unix_seconds;orders_sent\n"
ROW="12345;2;1;1;1;EURUSD;1.10000000;1.10020000;1720000000;0\n"

class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/FILENAME
    def tearDown(self): self.tmp.cleanup()
    def write(self, value=ROW): self.path.write_text(HEADER+value, encoding="utf-8")
    def test_valid(self):
        self.write()
        snap=parse_snapshot(self.path,"12345")
        self.assertEqual(snap["seq"],2)
        self.assertTrue(sanitized_report(snap)["demo_account"])
    def test_run_mismatch(self):
        self.write()
        with self.assertRaises(ValueError): parse_snapshot(self.path,"new-run")
    def test_no_order_violation(self):
        self.write(ROW.replace(";0\n",";1\n"))
        with self.assertRaises(ValueError): parse_snapshot(self.path,"12345")
    def test_invalid_spread(self):
        self.write(ROW.replace(";1.10020000;",";1.09900000;"))
        with self.assertRaises(ValueError): parse_snapshot(self.path,"12345")
    def test_lack_of_connection_is_reportable(self):
        self.write("12345;1;0;0;0;EURUSD;0;0;0;0\n")
        snap=parse_snapshot(self.path,"12345")
        self.assertFalse(sanitized_report(snap)["terminal_connected"])
    def test_find_in_wine_common_folder(self):
        prefix=Path(self.tmp.name)
        target=prefix/'drive_c/users/runner/AppData/Roaming/MetaQuotes/Terminal/Common/Files'
        target.mkdir(parents=True)
        (target/FILENAME).write_text(HEADER+ROW)
        self.assertEqual(find_snapshot(prefix,"12345")["seq"],2)

if __name__=='__main__':unittest.main()
