# Changelog

(C) Copyright 2021-2022 Hewlett Packard Enterprise Development LP.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.2] - 2022-06-16

### Changed
- Made changes related to the open sourcing of shasta-install-utility-common
    - Update Jenkinsfile to use csm-shared-library.
    - Add Makefile for building python package.
    - Update the version of nexusctl being used.

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
