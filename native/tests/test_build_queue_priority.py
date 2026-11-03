import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import build_queue_priority as queue


class QueuePriorityTests(unittest.TestCase):
    def test_runnable_deliveries_win_but_terminal_and_future_retries_do_not(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(queue,'STORE',Path(temporary)):
            job=Path(temporary)/'jobs'/'app';job.mkdir(parents=True)
            (job/'ready.json').write_text('{}')
            state=job/'state.json'
            state.write_text(json.dumps({'phase':'queued'}))
            self.assertEqual(queue.queued_delivery(now=1000),'app')
            for phase in queue.TERMINAL:
                state.write_text(json.dumps({'phase':phase}))
                self.assertIsNone(queue.queued_delivery(now=1000))
            state.write_text(json.dumps({'phase':'waiting_mac','nextAttempt':1010}))
            self.assertIsNone(queue.queued_delivery(now=1000))
            self.assertEqual(queue.queued_delivery(now=1010),'app')
            (job/'cancelled.json').write_text('{}')
            self.assertIsNone(queue.queued_delivery(now=1010))

    def test_incoming_push_gets_priority_before_upload_and_expires_after_interruption(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(queue,'STORE',Path(temporary)):
            job=Path(temporary)/'jobs'/'incoming';job.mkdir(parents=True)
            (job/'incoming.json').write_text(json.dumps({'at':1000}))
            self.assertEqual(queue.queued_delivery(now=1001),'incoming')
            self.assertIsNone(queue.queued_delivery(now=1600))
