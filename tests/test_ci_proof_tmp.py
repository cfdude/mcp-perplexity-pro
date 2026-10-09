"""Throwaway: fails only when CI=true, to prove a failing test turns the CI run red."""

import os


def test_fails_only_in_ci():
    assert os.environ.get("CI") != "true"
