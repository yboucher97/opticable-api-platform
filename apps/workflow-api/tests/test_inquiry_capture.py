from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from workflow.automation.phase9_form_receipts import FormReceiptLedger,parse_notification
from test_phase9_form_receipts import MESSAGE,DETAILS,HEADERS,HTML,NOW


class InquiryCaptureTests(unittest.TestCase):
 def parse(self,attempt):
  context={'schema':1,'language':'fr','attribution':{'inquiry_id':attempt,'first_campaign_id':'native-campaign-123','origin_path':'/fr/services/systemes-cameras-securite/'}}
  markup=HTML+'<table><tr><td>OptiBrain Acquisition Context</td><td>:</td><td>'+json.dumps(context)+'</td></tr></table>'
  return parse_notification(message_id=MESSAGE,details=DETAILS,content={'content':markup},headers=HEADERS,now=NOW)
 def test_real_notification_parser_preserves_id_and_deduplicates(self):
  receipt=self.parse('obq_'+'1'*32)
  self.assertEqual(receipt['attribution']['inquiry_id'],'obq_'+'1'*32)
  with tempfile.TemporaryDirectory() as d:
   store=FormReceiptLedger(Path(d)/'isolated.db')
   # Use the established immutable receipt insertion path.
   first=store.record(receipt);second=store.record(receipt)
   self.assertEqual(first,'CREATED');self.assertEqual(second,'REPLAY');self.assertEqual(len(store.list()),1)
 def test_invalid_attempt_id_is_rejected_before_persistence(self):
  for invalid in ('owner@example.invalid','obq_bad','obq_'+'z'*32):
   with self.subTest(invalid=invalid),self.assertRaises(ValueError):self.parse(invalid)
