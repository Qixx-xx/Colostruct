"""Pytest configuration for the A-group test package.

Intentionally empty of schema/path manipulation: pytest collection must not
replace ``core.pathology_schema`` or inject a stub. Schema-dependent tests use
the real backend module from the official checkout.
"""
