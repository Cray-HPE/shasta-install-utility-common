#!/bin/bash
# (C) Copyright 2021 Hewlett Packard Enterprise Development LP.

# Set PIP_EXTRA_INDEX_URL to pull in cray-product-catalog dependency for unit tests.
PIP_EXTRA_INDEX_URL="https://arti.dev.cray.com/artifactory/csm-python-modules-remote/simple/" pip3 install -r requirements.txt
pip3 install -r requirements-dev.txt
