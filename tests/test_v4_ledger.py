import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ascendra.v4_ledger import (FileLedger, BudgetExceeded, IntegrityError,
                                InfrastructureFailure, ProviderFailure, UncertainCall)


def concurrent_call(directory, queue):
    ledger = FileLedger(directory, 'config')
    def invoke(request):
        with (Path(directory) / 'physical_calls').open('a') as stream:
            stream.write('call\n')
        return {'answer': 42}, {'total_tokens': 5}
    queue.put(ledger.execute('same', {'reserved_tokens': 10}, invoke)[0])


def killed_call(directory):
    ledger = FileLedger(directory, 'config')
    ledger.execute('killed', {'reserved_tokens': 100}, lambda r: os._exit(17))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def ledger(self, **budgets):
        return FileLedger(self.tmp.name, 'config', budgets)

    def test_completed_cache_and_identity(self):
        ledger = self.ledger()
        req = {'reserved_tokens': 100}
        result = ledger.execute('one', req, lambda r: ('answer', {'input_tokens': 3, 'output_tokens': 5}))
        self.assertIsNone(result[1]['cost'])
        self.assertEqual(result, ledger.execute('one', req, lambda r: self.fail('duplicate')))
        self.assertEqual(ledger.summary()['known_tokens'], 8)
        with self.assertRaises(IntegrityError):
            ledger.execute('one', {**req, 'prompt': 'changed'}, None)
        with self.assertRaises(IntegrityError):
            FileLedger(self.tmp.name, 'new-config')

    def test_reservation_visible_before_call_and_interruption_failclosed(self):
        ledger = self.ledger()
        def interrupt(request):
            state = json.loads(ledger.path.read_text())['state']
            self.assertEqual(state['entries']['one']['attempts'][0]['status'], 'reserved')
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            ledger.execute('one', {'reserved_tokens': 100}, interrupt)
        resumed = self.ledger()
        with self.assertRaises(UncertainCall):
            resumed.execute('one', {'reserved_tokens': 100}, None)
        self.assertEqual(resumed.summary()['accounted_tokens'], 100)
        self.assertEqual(resumed.summary()['unknown_usage_calls'], 1)
        self.assertIsNone(resumed.summary()['cost'])

    def test_explicit_retry_once_and_known_failure_usage(self):
        ledger = self.ledger(allow_infrastructure_retry=True)
        req = {'reserved_tokens': 100}
        def failure(request):
            raise InfrastructureFailure('timeout', usage={'total_tokens': 9})
        for i in range(2):
            with self.assertRaises(InfrastructureFailure):
                ledger.execute('one', req, failure)
        with self.assertRaises(UncertainCall):
            ledger.execute('one', req, failure)
        self.assertEqual(ledger.summary()['calls'], 2)
        self.assertEqual(ledger.summary()['known_tokens'], 18)
        self.assertEqual(ledger.summary()['infra_retries'], 1)

    def test_noninfra_failure_never_retries(self):
        ledger = self.ledger(allow_infrastructure_retry=True)
        def failure(request):
            raise ProviderFailure('auth', usage={'total_tokens': 7})
        with self.assertRaises(ProviderFailure):
            ledger.execute('one', {'reserved_tokens': 100}, failure)
        with self.assertRaises(UncertainCall):
            ledger.execute('one', {'reserved_tokens': 100}, failure)
        self.assertEqual(ledger.summary()['known_tokens'], 7)

    def test_integrity_and_missing_state(self):
        ledger = self.ledger()
        data = json.loads(ledger.path.read_text())
        data['state']['entries']['forged'] = {}
        ledger.path.write_text(json.dumps(data))
        with self.assertRaises(IntegrityError):
            ledger.summary()
        ledger.path.unlink()
        with self.assertRaises(IntegrityError):
            self.ledger()

    def test_token_reservation_and_actual_overage_stop_admission(self):
        ledger = self.ledger(tokens=100)
        ledger.execute('one', {'reserved_tokens': 100}, lambda r: ('answer', {'total_tokens': 120}))
        self.assertEqual(ledger.summary()['accounted_tokens'], 120)
        self.assertFalse(ledger.summary()['provider_hard_token_limit_enforced'])
        with self.assertRaises(BudgetExceeded):
            ledger.execute('two', {'reserved_tokens': 1}, None)

    def test_unknown_usage_not_zero_and_call_phase_time_caps(self):
        ledger = self.ledger(tokens=100, calls=2, phase_caps={'development': 1})
        ledger.execute('one', {'reserved_tokens': 80}, lambda r: ('answer', {}))
        self.assertEqual(ledger.summary()['accounted_tokens'], 80)
        with self.assertRaises(BudgetExceeded):
            ledger.execute('two', {'reserved_tokens': 1}, None)

    def test_global_retry_cap(self):
        ledger = self.ledger(allow_infrastructure_retry=True, infra_retries=0)
        def failure(request):
            raise InfrastructureFailure('timeout')
        with self.assertRaises(InfrastructureFailure):
            ledger.execute('one', {'reserved_tokens': 10}, failure)
        with self.assertRaises(BudgetExceeded):
            ledger.execute('one', {'reserved_tokens': 10}, failure)

    def test_process_lock_prevents_completed_duplicates(self):
        ctx = multiprocessing.get_context('fork')
        queue = ctx.Queue()
        processes = [ctx.Process(target=concurrent_call, args=(self.tmp.name, queue)) for _ in range(3)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual([queue.get(timeout=1) for _ in processes], [{'answer': 42}] * 3)
        self.assertEqual((Path(self.tmp.name) / 'physical_calls').read_text(), 'call\n')

    def test_call_cap_independently(self):
        ledger = self.ledger(calls=1)
        ledger.execute('one', {'reserved_tokens': 10}, lambda r: ('answer', {}))
        with self.assertRaisesRegex(BudgetExceeded, 'Physical call'):
            ledger.execute('two', {'reserved_tokens': 1}, None)

    def test_time_cap_independently(self):
        ledger = self.ledger()
        with patch('ascendra.v4_ledger.time.time', return_value=10**12):
            with self.assertRaisesRegex(BudgetExceeded, 'Wall-time'):
                ledger.execute('one', {'reserved_tokens': 1}, None)
        self.assertEqual(ledger.summary()['calls'], 0)

    def test_unknown_usage_reservation_blocks_admission(self):
        ledger = self.ledger(tokens=100)
        ledger.execute('one', {'reserved_tokens': 80}, lambda r: ('answer', {}))
        with self.assertRaisesRegex(BudgetExceeded, 'Token admission'):
            ledger.execute('two', {'reserved_tokens': 21}, None)

    def test_hard_process_death_preserves_reservation(self):
        ctx = multiprocessing.get_context('fork')
        process = ctx.Process(target=killed_call, args=(self.tmp.name,))
        process.start()
        process.join(10)
        self.assertEqual(process.exitcode, 17)
        ledger = self.ledger()
        with self.assertRaises(UncertainCall):
            ledger.execute('killed', {'reserved_tokens': 100}, None)
        self.assertEqual(ledger.summary()['accounted_tokens'], 100)
