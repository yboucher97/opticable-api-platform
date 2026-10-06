import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('post37_sampler',Path(__file__).resolve().parents[3]/'ops/phase14/runtime_snapshot.py')
sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)


def props(**extra):
    return dict(LoadState='loaded',ActiveState='inactive',SubState='dead',Result='success',ExecMainStatus='0',
                ExecMainStartTimestampMonotonic='800000000',ExecMainExitTimestampMonotonic='900000000',
                ActiveEnterTimestampMonotonic='0',TimeoutStartUSec='5min',RuntimeMaxUSec='infinity',**extra)


class TimerHealthTests(unittest.TestCase):
    def check(self, expected, **extra):
        self.assertEqual(sampler.classify_job({**props(),**extra},uptime=1000,freshness_seconds=200)['state'],expected)

    def test_running_exit_zero(self):self.check('RUNNING',ActiveState='activating',SubState='start',ExecMainExitTimestampMonotonic='0')
    def test_running_under_timeout(self):self.check('RUNNING',ActiveState='activating',SubState='start',TimeoutStartUSec='3min 30s',ExecMainExitTimestampMonotonic='0')
    def test_running_beyond_timeout(self):self.check('TIMED_OUT',ActiveState='activating',SubState='start',TimeoutStartUSec='1min',ExecMainExitTimestampMonotonic='0')
    def test_previous_success_current_running(self):self.check('RUNNING',ActiveState='activating',SubState='start',ExecMainStartTimestampMonotonic='950000000',ExecMainExitTimestampMonotonic='900000000')
    def test_previous_failure_current_running(self):self.check('RUNNING',ActiveState='activating',SubState='start',Result='exit-code',ExecMainStatus='1',ExecMainExitTimestampMonotonic='0')
    def test_completed_success_fresh_active_enter_zero(self):self.check('COMPLETED_SUCCESS')
    def test_completed_remain_after_exit(self):self.check('COMPLETED_SUCCESS',ActiveState='active',SubState='exited')
    def test_completed_stale(self):self.check('STALE_COMPLETION',ExecMainStartTimestampMonotonic='600000000',ExecMainExitTimestampMonotonic='700000000')
    def test_failed(self):self.check('FAILED',ActiveState='failed',SubState='failed',Result='exit-code',ExecMainStatus='1')
    def test_timeout(self):self.check('TIMED_OUT',ActiveState='failed',SubState='failed',Result='timeout')
    def test_never_run(self):self.check('NEVER_RUN',ExecMainStartTimestampMonotonic='0',ExecMainExitTimestampMonotonic='0')
    def test_malformed_timestamp(self):self.check('UNKNOWN',ExecMainExitTimestampMonotonic='NaN')
    def test_future_timestamp(self):self.check('UNKNOWN',ExecMainExitTimestampMonotonic='1001000000')
    def test_reboot_timebase_mismatch(self):self.check('UNKNOWN',ExecMainStartTimestampMonotonic='950000000',ExecMainExitTimestampMonotonic='900000000')
    def test_unloaded(self):self.check('UNKNOWN',LoadState='not-found')
    def test_unreadable(self):self.assertEqual(sampler.classify_job({},uptime=1000,freshness_seconds=200)['state'],'UNKNOWN')
    def test_malformed_timeout(self):self.check('UNKNOWN',ActiveState='activating',SubState='start',TimeoutStartUSec='bad')
    def test_running_without_start(self):self.check('UNKNOWN',ActiveState='activating',SubState='start',ExecMainStartTimestampMonotonic='0')
    def test_active_timer_does_not_imply_completion(self):
        self.assertEqual(sampler.timer_summary([{'state':'RUNNING','timer_active':True}])['state'],'OK')
        self.assertEqual(sampler.timer_summary([{'state':'NEVER_RUN','timer_active':True}])['state'],'UNKNOWN')
    def test_inactive_timer_is_independent_failure(self):
        self.assertEqual(sampler.timer_summary([{'state':'COMPLETED_SUCCESS','timer_active':False}])['state'],'ACTION REQUIRED')
    def test_authority_excluded_job(self):
        self.assertNotIn('opticable-lifecycle-internal',sampler.expected_jobs({'internal':{'authority':'NOT AUTHORIZED'}}))
        self.assertIn('opticable-lifecycle-internal',sampler.expected_jobs({'internal':{'authority':'AUTHORIZED'}}))
