"""
setup.py - makes the Grad Cafe analytics service an installable package.

Why package it?  ``pip install -e .`` (or ``uv pip install -e .``) puts
``module_5/src`` on the import path *once*, so ``import flask_app`` behaves the
same in a terminal, under pytest, in CI and in a fresh clone - no sys.path
tricks, no "works on my machine" path problems.  The editable install keeps
edits live, tools such as ``uv`` can read the dependencies from here, and
``gradcafe-web`` / ``gradcafe-load`` become real console commands.
"""

from pathlib import Path

from setuptools import setup

HERE = Path(__file__).resolve().parent
RUNTIME_REQUIREMENTS = [
    line.split("#", 1)[0].strip()
    for line in (HERE / "requirements.txt").read_text(encoding="utf-8").splitlines()
    if line.split("#", 1)[0].strip()
]

setup(
    name="gradcafe-analytics",
    version="5.0.0",
    description="Grad Cafe admissions scraper, PostgreSQL loader and Flask analysis page (JHU Software Concepts)",
    long_description=(HERE / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="Pammi",
    python_requires=">=3.10",
    package_dir={"": "src"},
    py_modules=["clean", "config", "flask_app", "load_data", "models", "orm_queries",
                "pull_new_data", "query_data", "query_safety", "scrape", "standardize"],
    include_package_data=True,
    install_requires=RUNTIME_REQUIREMENTS,
    entry_points={
        "console_scripts": [
            "gradcafe-web=flask_app:main",
            "gradcafe-load=load_data:main",
            "gradcafe-query=query_data:main",
            "gradcafe-pull=pull_new_data:main",
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Framework :: Flask",
        "Topic :: Education",
    ],
)
