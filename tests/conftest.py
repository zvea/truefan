"""Global test configuration.

Prevents tests from accidentally reading the real truefan.toml by
ensuring the default config path resolves to a nonexistent location.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_from_real_config(tmp_path, monkeypatch):
    """Make the default config path point to a temp directory.

    Any test that accidentally relies on the real truefan.toml will
    get a FileNotFoundError instead of silently using production config.
    """
    monkeypatch.setattr(
        "truefan.main._default_config_path",
        lambda: tmp_path / "truefan.toml",
    )
