"""Sphinx configuration"""

# pylint: disable=invalid-name

# -- Imports ------------------------------------------------------------------

from pathlib import Path
from datetime import datetime
from yaml import dump

from fastapi.openapi.utils import get_openapi
from sphinx_pyproject import SphinxConfig

from icoapi.api import app as webapp

# -- Project information ------------------------------------------------------

sphinx_directory = Path(__file__).parent
config = SphinxConfig(
    sphinx_directory.parent.parent / "pyproject.toml", globalns=globals()
)
# pylint: disable=redefined-builtin,undefined-variable
copyright = f"{datetime.now().year}, {author}"  # type: ignore[name-defined]
# pylint: enable=redefined-builtin
project = name  # type: ignore[name-defined]
# pylint: enable=undefined-variable

# -- General configuration ----------------------------------------------------

extensions = [
    "myst_parser",
    "sphinxcontrib.openapi",
]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- HTML Theme ---------------------------------------------------------------

html_theme = "sphinx_rtd_theme"

# -- Myst ---------------------------------------------------------------------

myst_enable_extensions = [
    "dollarmath",
]

# pylint: enable=invalid-name

# -- Setup --------------------------------------------------------------------


def setup(app):  # pylint: disable=unused-argument
    """Create YAML file for OpenAPI spec"""

    print("📚 Generate OpenAPI specification file")
    spec = get_openapi(
        title=webapp.title,
        version=webapp.version,
        description=webapp.description,
        routes=webapp.routes,
    )
    with open(
        sphinx_directory / "openapi.yaml", "w", encoding="utf-8"
    ) as spec_file:
        dump(spec, spec_file)
