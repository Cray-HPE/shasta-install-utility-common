# Changelog

(C) Copyright 2021-2022 Hewlett Packard Enterprise Development LP

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.2] - 2022-06-24

### Changed
- Changed the format of copyright text and added MIT License text in all of the
  source files.

## [2.3.1] - 2022-05-25

### Changed
- Made changes related to the open sourcing of shasta-install-utility-common
    - Update Jenkinsfile to use csm-shared-library.
    - Add Makefile for building python package.

## [2.3.0] - 2022-04-06

### Changed

- Added support for HTTP authentication to Nexus using credentials stored
  in a Kubernetes secret. Updated minimum version of Nexusctl and began pulling
  this requirement from an internal pip repository rather than from VCS.

## [2.2.1] - 2022-01-04

### Changed

- Update to version 1.3.2 of ``cray-product-catalog`` and use the new
  ``SET_ACTIVE_VERSION`` variable to set the active version.

## [2.2.0] - 2021-11-11

### Added

- Added a method to activate an entry within the product catalog.

### Changed

- Changed the ProductCatalog to ignore products that don't match schema.

## [2.1.1] - 2021-11-10

### Added

- Added a ``clone_url`` property to ``InstalledProductVersion`` objects.

### Fixed

- Fetch ``cray-product-catalog`` from internal ``arti.dev.cray.com`` instead of
  ``artifactory.algol60.net`` to work around DNS issues in CJE.

## [2.1.0] - 2021-10-27

### Added

- Added common command-line options to a ``parser`` module.

## [2.0.0] - 2021-10-06

### Changed

- Renamed the library and Python package ``shasta-install-utility-common``.

## [1.0.0] - 2021-09-15

### Added

- Added ``install_utility_common`` package which can be imported by other
  product install utlities, based on code from ``sat-install-utility``.
