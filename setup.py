"""Packaging for the hf-tools Kotak Neo CLI suite.

The source lives in the ``hf-tools/`` directory but is imported as the
``hf_tools`` package (Python identifiers cannot contain hyphens), so we map
the directory explicitly via ``package_dir``.
"""

from setuptools import setup

setup(
    name="hf-tools",
    version="0.1.0",
    description="CLI tools for the Kotak Neo trading platform (hf-* suite).",
    author="idrinkcoffee",
    python_requires=">=3.8",
    package_dir={"hf_tools": "hf-tools"},
    packages=["hf_tools"],
    install_requires=[
        # The Kotak Neo SDK is installed from git; pin to the v2 line.
        # pip install "git+https://github.com/Kotak-Neo/Kotak-neo-api-v2.git@v2.0.1#egg=neo_api_client"
        "neo_api_client",
        "python-dotenv",
    ],
    entry_points={
        "console_scripts": [
            "hf = hf_tools.hf:main",
            # Individual nf-* style aliases.
            "hf-login = hf_tools.hf_login:main",
            "hf-order = hf_tools.hf_order:main",
            "hf-cancel = hf_tools.hf_cancel:main",
            "hf-modify = hf_tools.hf_modify:main",
            "hf-positions = hf_tools.hf_positions:main",
            "hf-portfolio = hf_tools.hf_portfolio:main",
            "hf-tradebook = hf_tools.hf_tradebook:main",
            "hf-orderbook = hf_tools.hf_orderbook:main",
            "hf-funds = hf_tools.hf_funds:main",
            "hf-logout = hf_tools.hf_logout:main",
        ]
    },
)
