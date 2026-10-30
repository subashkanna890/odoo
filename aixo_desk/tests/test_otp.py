from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import DeskCase


@tagged('post_install', '-at_install')
class TestOtp(DeskCase):

    def setUp(self):
        super().setUp()
        self.Otp = self.env['aixo.otp']

    def test_code_is_six_digits_and_hashed(self):
        code, record = self.Otp.issue(self.agent_a)
        self.assertRegex(code, r'^\d{6}$')
        self.assertNotIn(code, record.code_hash)
        self.assertTrue(self.Otp.verify(self.agent_a, code))

    def test_wrong_code_counts_attempts_then_locks(self):
        code, record = self.Otp.issue(self.agent_a)
        wrong = '000000' if code != '000000' else '111111'
        for _i in range(5):
            self.assertFalse(self.Otp.verify(self.agent_a, wrong))
        self.assertEqual(record.attempts, 5)
        self.assertFalse(self.Otp.verify(self.agent_a, code), "locked after 5 attempts even with the right code")

    def test_expiry(self):
        code, record = self.Otp.issue(self.agent_a)
        record.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.assertFalse(self.Otp.verify(self.agent_a, code))

    def test_resend_throttle(self):
        first, _record = self.Otp.issue(self.agent_a)
        self.assertTrue(first)
        again, _record = self.Otp.issue(self.agent_a)
        self.assertIsNone(again, "a second code within 30s is refused")
        _record.last_sent = fields.Datetime.now() - timedelta(seconds=31)
        newer, _record = self.Otp.issue(self.agent_a)
        self.assertTrue(newer)
        self.assertFalse(self.Otp.verify(self.agent_a, first) and first != newer,
                         "issuing a new code invalidates the old one")

    def test_consumed_code_cannot_be_reused(self):
        code, _record = self.Otp.issue(self.agent_a)
        record = self.Otp.verify(self.agent_a, code)
        record.consume()
        self.assertFalse(self.Otp.verify(self.agent_a, code))

    def test_codes_are_per_user(self):
        code, _record = self.Otp.issue(self.agent_a)
        self.assertFalse(self.Otp.verify(self.agent_b, code))
