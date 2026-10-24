"""Machine-learning helpers for Ananke.

Currently holds a single, hold-out-validated surrogate model that gives a fast
approximate preview of orbital lifetime. It is a preview aid only and is never
used for compliance (PASS/FAIL) decisions — see :mod:`ananke.ml.surrogate`.
"""
