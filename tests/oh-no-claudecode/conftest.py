"""Pytest configuration for oh-no-claudecode tests."""

import sys
from pathlib import Path

import pytest

# Add plugin scripts to path so we can import server_lifecycle
_scripts_dir = str(
    Path(__file__).resolve().parent.parent.parent
    / "plugins/oh-no-claudecode/scripts"
)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from server_lifecycle import (  # noqa: E402
    OPENCODE_SERVER_PORT,
    opencode_acquire,
    opencode_release,
)


# Pytest hooks and fixtures


def pytest_addoption(parser):
    parser.addoption(
        "--skip-opencode",
        action="store_true",
        default=False,
        help="Skip tests that require OpenCode service",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "opencode: marks tests as requiring OpenCode service"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--skip-opencode"):
        skip_opencode = pytest.mark.skip(reason="--skip-opencode flag provided")
        for item in items:
            if "opencode" in item.keywords:
                item.add_marker(skip_opencode)
    else:
        # Auto-wire opencode_server fixture for opencode-marked tests so they
        # get server lifecycle management and skip when OpenCode is unavailable.
        for item in items:
            if "opencode" in item.keywords:
                item.add_marker(pytest.mark.usefixtures("opencode_server"))


@pytest.fixture(scope="session")
def opencode_server():
    """Session-scoped fixture that ensures OpenCode server is running.

    Uses reference counting so multiple test sessions can share one server.
    NOT autouse — only tests that request this fixture or use the opencode mark need it.
    Unit tests run without OpenCode.
    """
    available = opencode_acquire()
    if not available:
        pytest.skip("OpenCode not available")

    yield f"http://127.0.0.1:{OPENCODE_SERVER_PORT}"

    opencode_release()


@pytest.fixture
def opencode_available(opencode_server):
    """Fixture that provides OpenCode server URL. Marks test as requiring OpenCode."""
    return opencode_server
