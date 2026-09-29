"""Sphinx configuration for the Grad Cafe analytics service (Module 4)."""

import os
import sys

# Make module_4/src importable for autodoc.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

project = "Grad Cafe Analytics"
author = "Pammi"
release = "4.0"
copyright = "2026, Pammi"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
]

autodoc_member_order = "bysource"
autodoc_default_options = {"members": True, "undoc-members": True, "show-inheritance": True, "exclude-members": "metadata,registry"}
# Heavy/optional runtime dependencies are mocked so the docs build anywhere (e.g. Read the Docs).
autodoc_mock_imports = ["selenium", "llama_cpp", "huggingface_hub"]
napoleon_google_docstring = True
napoleon_numpy_docstring = True

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_title = "Grad Cafe Analytics"
