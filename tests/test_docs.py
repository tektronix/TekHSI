"""Test for the documentation."""

import os
import subprocess
import sys
import time

from collections.abc import Generator
from importlib.util import find_spec
from pathlib import Path

import pytest

PROJECT_ROOT_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(name="docs_server")
def fixture_docs_server(site_dir: str) -> Generator[str, None, None]:
    """Serve the documentation site."""
    port = f"8{sys.version_info.major}{sys.version_info.minor}"
    cmd = [sys.executable, "-m", "http.server", port, "--directory", site_dir]
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as server_process:
        time.sleep(1)  # wait for server to start

        yield f"http://127.0.0.1:{port}/"

        server_process.terminate()  # stop the server
        try:
            server_process.wait(timeout=10)  # Wait up to 10 seconds for the server to terminate
        except subprocess.TimeoutExpired:
            server_process.kill()  # Force kill if it doesn't terminate in time


@pytest.fixture(name="site_dir", scope="session")
def fixture_site_dir(pytestconfig: pytest.Config) -> str:
    """Create the site directory path for testing."""
    site_path = (
        PROJECT_ROOT_DIR / f".site_{sys.version_info.major}{sys.version_info.minor}/"
    ).resolve()
    if xml_path := pytestconfig.getoption("xmlpath"):
        site_path = Path(xml_path).parent / ".site_html/"  # pyright: ignore[reportArgumentType]
        site_path = site_path.resolve()
    site_path.mkdir(parents=True, exist_ok=True)
    return site_path.as_posix()


@pytest.fixture(scope="module", autouse=True)
def _docs_tests_setup() -> Generator[None, None, None]:  # pyright: ignore [reportUnusedFunction]
    """Setup for docs tests.."""
    starting_directory = Path.cwd()
    try:
        os.chdir(PROJECT_ROOT_DIR)
        yield
    finally:
        os.chdir(starting_directory)


@pytest.mark.docs
@pytest.mark.slow
@pytest.mark.skipif(find_spec("mkdocs") is None, reason="The mkdocs package is not installed.")
class TestDocs:  # pylint: disable=no-self-use
    """A collection of documentation tests."""

    @pytest.mark.order(1)
    def test_docs_html(self, site_dir: str) -> None:
        """Test creating html documentation."""
        config_file = PROJECT_ROOT_DIR / "mkdocs.yml"
        assert config_file.is_file(), f"Missing MkDocs configuration: {config_file}"
        subprocess.check_call(
            [
                "mkdocs",
                "build",
                f"--config-file={config_file}",
                "--verbose",
                f"--site-dir={site_dir}",
            ],
        )

    @pytest.mark.order(2)
    @pytest.mark.depends(on=["test_docs_html"])
    def test_docs_linkcheck(self, docs_server: str) -> None:
        """Run the linkcheck test for the documentation."""
        cmd = [
            "linkchecker",
            "--config=docs/.linkchecker.ini",
            # External badge endpoint occasionally returns transient gateway errors.
            "--ignore-url=https://codecov.io/.*",
            docs_server,
        ]
        subprocess.check_call(cmd)
