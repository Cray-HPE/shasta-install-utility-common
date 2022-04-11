"""
Contains common CLI arguments for install utility images.

(C) Copyright 2021-2022 Hewlett Packard Enterprise Development LP.
"""

import argparse

from shasta_install_utility_common.constants import (
    DEFAULT_DOCKER_URL,
    DEFAULT_NEXUS_URL,
    NEXUS_CREDENTIALS_SECRET_NAME,
    NEXUS_CREDENTIALS_SECRET_NAMESPACE,
    PRODUCT_CATALOG_CONFIG_MAP_NAME,
    PRODUCT_CATALOG_CONFIG_MAP_NAMESPACE
)


def create_parser():
    """Create an argument parser for this command.

    Returns:
        argparse.ArgumentParser: The parser.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument(
        'action',
        choices=['uninstall', 'activate'],
        help='Specify the operation to execute on a product.'
    )
    parser.add_argument(
        'version',
        help='Specify the version of the product to operate on.'
    )
    parser.add_argument(
        '--nexus-url',
        help='Override the base URL of Nexus.',
        default=DEFAULT_NEXUS_URL
    )
    parser.add_argument(
        '--docker-url',
        help='Override the base URL of the Docker registry.',
        default=DEFAULT_DOCKER_URL,
    )
    parser.add_argument(
        '--product-catalog-name',
        help='The name of the product catalog Kubernetes ConfigMap',
        default=PRODUCT_CATALOG_CONFIG_MAP_NAME
    )
    parser.add_argument(
        '--product-catalog-namespace',
        help='The namespace of the product catalog Kubernetes ConfigMap',
        default=PRODUCT_CATALOG_CONFIG_MAP_NAMESPACE
    )
    parser.add_argument(
        '--nexus-credentials-secret-name',
        help='The name of the kubernetes secret containing HTTP authentication '
             'credentials for Nexus.',
        default=NEXUS_CREDENTIALS_SECRET_NAME,
    )
    parser.add_argument(
        '--nexus-credentials-secret-namespace',
        help='The namespace of the kubernetes secret containing HTTP '
             'authentication credentials for Nexus.',
        default=NEXUS_CREDENTIALS_SECRET_NAMESPACE
    )

    return parser
