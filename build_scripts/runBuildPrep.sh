#!/bin/bash
# (C) Copyright 2021-2022 Hewlett Packard Enterprise Development LP.

# Set PIP_EXTRA_INDEX_URL to pull internal packages from internal locations:
# arti.dev.cray.com/artifactory/csm-python-modules-remote/simple/ - repo containing cray-product-catalog
# arti.dev.cray.com/artifactory/internal-pip-stable-local/ - repo containing nexusctl
PIP_EXTRA_INDEX_URL="https://arti.dev.cray.com/artifactory/csm-python-modules-remote/simple/
  https://arti.dev.cray.com/artifactory/internal-pip-stable-local/" pip3 install -r requirements.txt
pip3 install -r requirements-dev.txt
