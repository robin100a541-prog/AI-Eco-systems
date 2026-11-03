"""Verifies BL-009. Testar att AgentRegistry.set_guard validerar guard‑objektet."""

import unittest

from aie.agents import AgentRegistry, RegistryError


class TestSetGuard(unittest.TestCase):
    def test_set_guard_invalid(self):
        """Guard utan required‑metoden ska ge RegistryError."""
        registry = AgentRegistry(object(), object())

        class BadGuard:
            pass

        with self.assertRaises(RegistryError):
            registry.set_guard(BadGuard())

    def test_set_guard_valid(self):
        """Guard med transition_block_reason ska accepteras."""
        registry = AgentRegistry(object(), object())

        class GoodGuard:
            def transition_block_reason(self, agent_id, old, new, changed_by):
                return None

        # Ingen exception ska kastas
        registry.set_guard(GoodGuard())
