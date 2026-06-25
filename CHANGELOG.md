<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->
# Changelog for dailyerosion Python library

## Unreleased Version

### API Changes

### New Features

### Bug Fixes

## **1.1.3** (24 Jun 2026)

### API Changes

- Require python 3.11+.
- Updated to use `dep` relation from
  [akrherz/iem-database](https://github.com/akrherz/iem-database) repo.

### New Features

- Generalize `weps2sweep` workflow as just `weps`.
- Allow provision of the RabbitMQ settings file for `get_rabbitmqconn`.

### Bug Fixes

## **1.1.2** (12 Feb 2026)

- Renamed library to `dailyerosion`.

## **1.1.1** (12 Feb 2026)

- First release made to pypi and hopefully conda-forge.

### API Changes

### New Features

- Begin documenting changes within this CHANGELOG, how meta.

### Bug Fixes

- Add dailyerosion.util helper to fetch a RabbitMQ connection.
