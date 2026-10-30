"""Verifies M3/M4, DR-13, ER-19/21 and SR-12 at transport and tax boundaries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aie.config import ConfigError
from aie.ledger import EntryType, LedgerError
from aie.llm.providers import DataClass, OpenAICompatibleProvider
from aie.llm.router import load_providers
from aie.tax.engine import TaxError
from .test_tax_payment import PaymentCase


class LocalTransport(unittest.TestCase):
    def test_nonlocal_or_credentialed_ollama_endpoints_are_rejected_before_transport(self):
        bad = ("https://example.com/v1", "http://192.168.1.2/v1", "http://localhost.example/v1",
               "http://user:password@127.0.0.1/v1", "http://127.0.0.1/v1?route=remote", "file:///tmp/model")
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ValueError):
                OpenAICompatibleProvider("local", "ollama", "test", None, base_url=url)

    def test_literal_loopback_and_localhost_keep_internal_classification(self):
        for url in ("http://127.0.0.1:11434/v1", "http://[::1]:11434/v1", "https://localhost/v1"):
            with self.subTest(url=url):
                provider = OpenAICompatibleProvider("local", "ollama", "test", None, base_url=url)
                self.assertIn(DataClass.INTERNAL, provider.allowed_classes)

    def test_config_loader_reports_remote_ollama_as_config_error(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "providers.toml").write_text('config_version = 1\n[[providers]]\nname = "local"\n'
                'kind = "ollama"\nmodel = "test"\ndaily_calls = 10\ndaily_tokens = 1000\n'
                'base_url = "https://remote.example/v1"\n')
            with self.assertRaises(ConfigError):
                load_providers(folder, environ={})


class PaymentRecovery(PaymentCase):
    def test_payment_and_allocation_roll_back_together_then_retry_once(self):
        original = self.ledger.record
        before = self.ledger.entries()
        def fail_after_record(actor, draft):
            original(actor, draft)
            raise RuntimeError("interruption before tax allocation")
        with patch.object(self.ledger, "record", side_effect=fail_after_record):
            with self.assertRaises(RuntimeError):
                self.tax.pay("robin", "partnership", 2027, 1000, ("file:receipt-1",), payment_id="bank-1")
        self.assertEqual(self.ledger.entries(), before)
        self.assertEqual(self.tax.payments(), ())
        first = self.tax.pay("robin", "partnership", 2027, 1000, ("file:receipt-1",), payment_id="bank-1")
        retry = self.tax.pay("robin", "partnership", 2027, 1000, ("file:receipt-1",), payment_id="bank-1")
        self.assertEqual(first, retry)
        self.assertEqual(len(self.tax.payments()), 1)
        self.assertEqual(sum(e.amount_minor for e in self.ledger.entries()
                             if e.entry_type is EntryType.TAX_PAYMENT), 1000)

    def test_conflicting_amount_or_track_cannot_reuse_payment_identity(self):
        self.tax.pay("robin", "partnership", 2027, 1000, ("file:receipt-1",), payment_id="bank-1")
        with self.assertRaises(LedgerError):
            self.tax.pay("robin", "partnership", 2027, 2000, ("file:receipt-1",), payment_id="bank-1")
        with self.assertRaises(TaxError):
            self.tax.pay("robin", None, 2027, 1000, ("file:receipt-1",), payment_id="bank-1")
        self.assertEqual(len(self.tax.payments()), 1)
