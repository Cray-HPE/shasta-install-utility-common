#!/bin/bash
# (C) Copyright 2021 Hewlett Packard Enterprise Development LP.

# Build Python source distribution and wheel
pip3 install --upgrade pip setuptools wheel
python3 setup.py sdist bdist_wheel
