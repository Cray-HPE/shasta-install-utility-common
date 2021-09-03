"""
Unit tests for the install_utility_common.products module.

(C) Copyright 2021 Hewlett Packard Enterprise Development LP.

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
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
"""

import copy
from subprocess import CalledProcessError
import unittest
from unittest.mock import call, Mock, patch

from yaml import safe_dump

from install_utility_common.products import (
    ProductCatalog,
    ProductInstallException,
    InstalledProductVersion
)


MOCK_PRODUCT_CATALOG_DATA = {
    # Two versions of SAT that have no images in common with one another.
    'sat': safe_dump({
        '2.0.0': {'component_versions': {'docker': [
            {'name': 'cray/cray-sat', 'version': '1.0.0'},
            {'name': 'cray/sat-cfs-install', 'version': '1.4.0'}
        ]}},
        '2.0.1': {'component_versions': {'docker': [
            {'name': 'cray/cray-sat', 'version': '1.0.1'},
            {'name': 'cray/sat-other-image', 'version': '1.4.0'}
        ]}},
    }),
    # Two versions of COS, where one of the images is the same between them.
    'cos': safe_dump({
        '2.0.0': {'component_versions': {'docker': [
            {'name': 'cray/cray-cos', 'version': '1.0.0'},
            {'name': 'cray/cos-cfs-install', 'version': '1.4.0'}
        ]}},
        '2.0.1': {'component_versions': {'docker': [
            {'name': 'cray/cray-cos', 'version': '1.0.1'},
            {'name': 'cray/cos-cfs-install', 'version': '1.4.0'}
        ]}},
    }),
    # One version of "Other Product" that also uses cray/cray-sat:1.0.1
    'other_product': safe_dump({
        '2.0.0': {'component_versions': {'docker': [
            {'name': 'cray/cray-sat', 'version': '1.0.1'},
        ]}}
    })
}


class TestProductCatalog(unittest.TestCase):
    """Tests for the ProductCatalog class."""

    def setUp(self):
        """Set up mocks."""
        self.mock_k8s_api = Mock()
        self.mock_product_catalog_data = copy.deepcopy(MOCK_PRODUCT_CATALOG_DATA)
        self.mock_k8s_api.read_namespaced_config_map.return_value = Mock(data=self.mock_product_catalog_data)
        self.mock_environ = patch('install_utility_common.products.os.environ').start()
        self.mock_check_output = patch('install_utility_common.products.subprocess.check_output').start()
        self.mock_print = patch('builtins.print').start()
        self.mock_docker = Mock()

    def create_and_assert_product_catalog(self):
        """Assert the product catalog was created as expected."""
        product_catalog = ProductCatalog('mock-name', 'mock-namespace', self.mock_k8s_api)
        self.mock_k8s_api.read_namespaced_config_map.assert_called_once_with('mock-name', 'mock-namespace')
        return product_catalog

    def test_create_product_catalog(self):
        """Test creating a simple ProductCatalog."""
        product_catalog = self.create_and_assert_product_catalog()
        expected_names_and_versions = [
            (name, version) for name in ('sat', 'cos') for version in ('2.0.0', '2.0.1')
        ] + [('other_product', '2.0.0')]
        actual_names_and_versions = [
            (product.name, product.version) for product in product_catalog.products
        ]
        self.assertEqual(expected_names_and_versions, actual_names_and_versions)

    def test_create_product_catalog_invalid_product_data(self):
        """Test creating a ProductCatalog when the product catalog contains invalid data."""
        self.mock_product_catalog_data['sat'] = '\t'
        with self.assertRaisesRegex(ProductInstallException, 'Failed to load ConfigMap data'):
            self.create_and_assert_product_catalog()

    def test_create_product_catalog_null_data(self):
        """Test creating a ProductCatalog when the product catalog contains null data."""
        self.mock_k8s_api.read_namespaced_config_map.return_value = Mock(data=None)
        with self.assertRaisesRegex(ProductInstallException,
                                    'No data found in mock-namespace/mock-name ConfigMap.'):
            self.create_and_assert_product_catalog()

    def test_get_matching_products(self):
        """Test getting a particular product by name/version."""
        product_catalog = self.create_and_assert_product_catalog()
        expected_matching_name_and_version = ('cos', '2.0.0')
        expected_other_versions = [('sat', version) for version in ('2.0.0', '2.0.1', '2.0.2')]
        expected_other_versions.extend([('cos', version) for version in ('2.0.1', '2.0.2')])
        actual_matching_product = product_catalog.get_product('cos', '2.0.0')
        self.assertEqual(
            expected_matching_name_and_version, (actual_matching_product.name, actual_matching_product.version)
        )
        expected_component_data = {'component_versions': {'docker': [
            {'name': 'cray/cray-cos', 'version': '1.0.0'},
            {'name': 'cray/cos-cfs-install', 'version': '1.4.0'}
        ]}}
        self.assertEqual(expected_component_data, actual_matching_product.data)

    def test_remove_from_product_catalog(self):
        """Test removing a version from the product catalog."""
        product_catalog = self.create_and_assert_product_catalog()
        product_catalog.remove_product_entry('mock_name', 'mock_version')
        self.mock_environ.update.assert_called_once_with({
            'PRODUCT': 'mock_name',
            'PRODUCT_VERSION': 'mock_version',
            'CONFIG_MAP': 'mock-name',
            'CONFIG_MAP_NS': 'mock-namespace',
            'VALIDATE_SCHEMA': 'true'
        })
        self.mock_check_output.assert_called_once_with(['catalog_delete.py'])

    def test_remove_from_product_catalog_fail(self):
        """Test removing a version from the product catalog when the subcommand fails."""
        product_catalog = self.create_and_assert_product_catalog()
        expected_err_regex = (
            f'Error removing mock_name-mock_version from product catalog'
        )
        self.mock_check_output.side_effect = CalledProcessError(1, 'catalog_delete.py')
        with self.assertRaisesRegex(ProductInstallException, expected_err_regex):
            product_catalog.remove_product_entry('mock_name', 'mock_version')

    def test_remove_product_docker_images(self):
        """Test a basic removal of a product's docker images."""
        product_catalog = self.create_and_assert_product_catalog()
        with patch.object(InstalledProductVersion, 'uninstall_docker_image') as mock_uninstall_docker_image:
            product_catalog.remove_product_docker_images('sat', '2.0.0', self.mock_docker)
            mock_uninstall_docker_image.assert_has_calls([
                call('cray/cray-sat', '1.0.0', self.mock_docker),
                call('cray/sat-cfs-install', '1.4.0', self.mock_docker)
            ])

    def test_partial_remove_docker_images(self):
        """Test a removal of docker images when an image is shared."""
        product_catalog = self.create_and_assert_product_catalog()
        with patch.object(InstalledProductVersion, 'uninstall_docker_image') as mock_uninstall_docker_image:
            product_catalog.remove_product_docker_images('cos', '2.0.0', self.mock_docker)
            mock_uninstall_docker_image.assert_called_once_with(
                'cray/cray-cos', '1.0.0', self.mock_docker
            )
            self.mock_print.assert_called_once_with(
                'Not removing Docker image cray/cos-cfs-install:1.4.0 '
                'used by the following other product versions: cos-2.0.1'
            )

    def test_partial_remove_docker_images_other_product(self):
        """Test a removal when a product's only image is also used by another product."""
        product_catalog = self.create_and_assert_product_catalog()
        with patch.object(InstalledProductVersion, 'uninstall_docker_image') as mock_uninstall_docker_image:
            product_catalog.remove_product_docker_images('other_product', '2.0.0', self.mock_docker)
            mock_uninstall_docker_image.assert_not_called()
            self.mock_print.assert_called_once_with(
                'Not removing Docker image cray/cray-sat:1.0.1 used '
                'by the following other product versions: sat-2.0.1'
            )


class TestInstalledProductVersion(unittest.TestCase):
    def setUp(self):
        """Set up mocks."""
        self.installed_product_version = InstalledProductVersion(
            'sat',
            '2.2.0',
            {'component_versions': {'docker': [
                {'name': 'cray/cray-sat', 'version': '1.0.2'},
                {'name': 'cray/sat-cfs-install', 'version': '1.1.1'}
            ]}}
        )
        self.legacy_installed_product_version = InstalledProductVersion(
            'sat', '1.0.1', {'component_versions': {'sat': '1.0.0'}}
        )

        self.mock_nexus_api = Mock()
        self.mock_group_members = ['sat-3.0.0-sle-15sp3', 'sat-2.2.0-sle-15sp3', 'sat-1.0.1-sle-15sp3']
        self.mock_group_repo = Mock()
        self.mock_group_repo.group.member_names = self.mock_group_members
        # This is slightly incorrect as NexusApi.repos.list may also return a
        # hosted repo, but good enough for the test.
        self.mock_nexus_api.repos.list.return_value = [self.mock_group_repo]
        self.mock_docker_api = Mock()

    def tearDown(self):
        """Stop patches."""
        patch.stopall()

    def test_docker_images(self):
        """Test getting the Docker images."""
        expected_docker_image_versions = [('cray/cray-sat', '1.0.2'),
                                          ('cray/sat-cfs-install', '1.1.1')]
        self.assertEqual(
            expected_docker_image_versions, self.installed_product_version.docker_images
        )

    def test_legacy_docker_images(self):
        """Test getting the Docker images from an 'old'-style product catalog entry."""
        expected_docker_image_versions = [('cray/cray-sat', '1.0.0')]
        self.assertEqual(
            expected_docker_image_versions, self.legacy_installed_product_version.docker_images
        )

    def test_no_docker_images(self):
        """Test a product that has an empty dictionary under the 'docker' key returns an empty dictionary."""
        product_with_no_docker_images = InstalledProductVersion(
            'sat', '0.9.9', {'component_versions': {'docker': {}}}
        )
        self.assertEqual(product_with_no_docker_images.docker_images, [])

    def test_no_docker_images_null(self):
        """Test a product that has None under the 'docker' key returns an empty dictionary."""
        product_with_no_docker_images = InstalledProductVersion(
            'sat', '0.9.9', {'component_versions': {'docker': None}}
        )
        self.assertEqual(product_with_no_docker_images.docker_images, [])

    def test_no_docker_images_empty_list(self):
        """Test a product that has an empty list under the 'docker' key returns an empty dictionary."""
        product_with_no_docker_images = InstalledProductVersion(
            'sat', '0.9.9', {'component_versions': {'docker': []}}
        )
        self.assertEqual(product_with_no_docker_images.docker_images, [])

    def test_str(self):
        """Test the string representation of InstalledProductVersion."""
        expected_str = 'sat-2.2.0'
        self.assertEqual(
            expected_str, str(self.installed_product_version)
        )

    def test_get_group_repo_name(self):
        """Test getting a group repo name for an InstalledProductVersion."""
        expected_group_repo_name = 'sat-sle-15sp3'
        self.assertEqual(
            expected_group_repo_name, self.installed_product_version.get_group_repo_name('sle-15sp3')
        )

    def test_get_hosted_repo_name(self):
        """Test getting a hosted repo name for an InstalledProductVersion."""
        expected_hosted_repo_name = 'sat-2.2.0-sle-15sp3'
        self.assertEqual(
            expected_hosted_repo_name, self.installed_product_version.get_hosted_repo_name('sle-15sp3')
        )

    def test_uninstall_hosted_repo(self):
        """Test uninstalling a hosted repo for an InstalledProductVersion."""
        self.installed_product_version.uninstall_hosted_repo(self.mock_nexus_api, 'sle-15sp3')
        self.mock_nexus_api.repos.delete.assert_called_once_with('sat-2.2.0-sle-15sp3')

    def test_uninstall_docker_image(self):
        """Test uninstalling a Docker image for an InstalledProductVersion."""
        self.installed_product_version.uninstall_docker_image('foo', 'bar', self.mock_docker_api)
        self.mock_docker_api.delete_image.assert_called_once_with('foo', 'bar')

    def test_activate_hosted_repo(self):
        """Test activating a product version's hosted repository."""
        self.installed_product_version.activate_hosted_repo(self.mock_nexus_api, 'sle-15sp3')
        self.mock_nexus_api.repos.raw_group.update.assert_called_once_with(
            self.mock_group_repo.name,
            self.mock_group_repo.online,
            self.mock_group_repo.storage.blobstore_name,
            self.mock_group_repo.storage.strict_content_type_validation,
            member_names=('sat-2.2.0-sle-15sp3',)
        )


if __name__ == '__main__':
    unittest.main()
