#!/usr/bin/env python3
"""Run the repository's unittest regression with every IP socket disabled."""
import argparse
import json
from pathlib import Path
import socket
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'apps/workflow-api'
sys.path[:0] = [str(APP), str(APP / 'tests')]
FOCUSED = ['test_lifecycle_truth', 'test_phase37_manager', 'test_phase34_sales',
           'test_sales_intelligence', 'test_business_observation_runtime',
           'test_post37_completeness', 'test_post37_timer_health',
           'test_post37_release_preservation', 'test_customer_finance_evidence',
           'test_phase8_sales_queue', 'test_phase8_sales_operator_view']


class CountedResult(unittest.TextTestResult):
    subtests = 0

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        super().addSubTest(test, subtest, err)


def run(suite_name):
    attempts = []
    # AF_UNIX socketpairs used by the test event loop remain local. No IP
    # connection, UDP send, localhost provider or production API is permitted.
    def guard(method):
        original = getattr(socket.socket, method)
        def bounded(sock, *args, **kwargs):
            if sock.family in {socket.AF_INET, socket.AF_INET6}:
                attempts.append(method)
                raise AssertionError('Lifecycle regression forbids IP network access')
            return original(sock, *args, **kwargs)
        setattr(socket.socket, method, bounded)
    for method in ('connect', 'connect_ex', 'sendto', 'sendmsg'):
        if hasattr(socket.socket, method):
            guard(method)
    names = ['test_lifecycle_truth'] if suite_name == 'lifecycle' else FOCUSED
    suite = (unittest.defaultTestLoader.discover(str(APP / 'tests')) if suite_name == 'full'
             else unittest.defaultTestLoader.loadTestsFromNames(names))
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountedResult).run(suite)
    return {'suite': suite_name, 'tests': result.testsRun, 'subtests': result.subtests,
            'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': len(result.skipped), 'passed': result.wasSuccessful(),
            'network_policy': 'ALL_IP_SOCKETS_DENIED', 'blocked_socket_attempts': len(attempts),
            'provider_network_writes': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=['lifecycle', 'focused', 'full'], default='focused')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.suite)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, sort_keys=True))
    raise SystemExit(0 if summary['passed'] else 1)
