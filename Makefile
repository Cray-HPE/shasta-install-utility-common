# Copyright 2021 Hewlett Packard Enterprise Development LP
#
# Based on Makefile used in Cray-HPE/cray-product-catalog but without
# the use of cms_meta_tools.

NAME ?= shasta-install-utility-common

all: pymod_prepare pymod_build pymod_test

pymod_prepare:
		pip3 install --upgrade pip setuptools wheel

pymod_build:
		python3 setup.py sdist bdist_wheel

pymod_test:
		pip3 install -r requirements.txt
		pip3 install -r requirements-dev.txt
		mkdir -p pymod_test
		python3 setup.py install --user
		nosetests
		pycodestyle --config=pycodestyle.conf shasta_install_utility_common tests
