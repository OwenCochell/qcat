"""Build shim: generate the protobuf/gRPC stubs before packaging.

All static metadata lives in pyproject.toml; this file exists only to run
generate_stubs.py as part of the build so the _pb/ tree is present *before*
setuptools discovers packages, and therefore gets included in the wheel. See
generate_stubs.py for what that generation does.

The generation runs at import time (before setup() below) because setuptools
resolves [tool.setuptools.packages.find] while configuring the distribution,
which happens before any build command runs -- the generated packages must
already exist on disk by then to be discovered.
"""

import os
import sys

from setuptools import setup

# The build backend execs this script with the project root as cwd but not on
# sys.path, so make the sibling generate_stubs module importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generate_stubs

generate_stubs.main()

setup()
