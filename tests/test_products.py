#
# MIT License
#
# (C) Copyright 2021-2023 Hewlett Packard Enterprise Development LP
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
"""
Unit tests for the shasta_install_utility_common.products module.
"""

import copy
import unittest
from base64 import b64decode
from http.client import HTTPResponse
from re import U
from subprocess import CalledProcessError
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch
from urllib.error import HTTPError
from urllib.request import Request

from kubernetes.client import V1ConfigMap
from kubernetes.client.rest import ApiException
from kubernetes.config import ConfigException
from nexusctl.common import HttpMethod
from urllib3.exceptions import MaxRetryError
from yaml import safe_dump

from shasta_install_utility_common.constants import (
    PRODUCT_CATALOG_CONFIG_MAP_NAME, PRODUCT_CATALOG_CONFIG_MAP_NAMESPACE)
from shasta_install_utility_common.products import (InstalledProductVersion,
                                                    ProductCatalog,
                                                    ProductInstallException,
                                                    uninstall_docker_image,
                                                    uninstall_k8_helm_charts,
                                                    uninstall_nexus_helm_chart)
from tests.mocks import (MOCK_K8S_CRED_SECRET_DATA,
                         MOCK_K8S_HELM_CHARTS_COMPONENTS,
                         MOCK_PRODUCT_CATALOG_DATA,
                         MOCK_PRODUCT_CATALOG_DATA_HELM_TESTS, SAT_VERSIONS)


class TestGetK8sAPI(unittest.TestCase):
    """Tests for ProductCatalog.get_k8s_api()."""

    def setUp(self):
        """Set up mocks."""
        self.mock_load_kube_config = patch('shasta_install_utility_common.products.load_kube_config').start()
        self.mock_corev1api = patch('shasta_install_utility_common.products.CoreV1Api').start()

    def tearDown(self):
        """Stop patches."""
        patch.stopall()

    def test_get_k8s_api(self):
        """Test the successful case of get_k8s_api."""
        api = ProductCatalog._get_k8s_api()
        self.mock_load_kube_config.assert_called_once_with()
        self.mock_corev1api.assert_called_once_with()
        self.assertEqual(api, self.mock_corev1api.return_value)

    def test_get_k8s_api_config_exception(self):
        """Test when configuration can't be loaded."""
        self.mock_load_kube_config.side_effect = ConfigException
        with self.assertRaises(ProductInstallException):
            ProductCatalog._get_k8s_api()
        self.mock_load_kube_config.assert_called_once_with()
        self.mock_corev1api.assert_not_called()


class TestProductCatalog(unittest.TestCase):
    """Tests for the ProductCatalog class."""

    def setUp(self):
        """Set up mocks."""
        self.mock_k8s_api = patch.object(ProductCatalog, '_get_k8s_api').start().return_value
        self.mock_product_catalog_data = copy.deepcopy(MOCK_PRODUCT_CATALOG_DATA)
        self.mock_k8s_api.read_namespaced_config_map.return_value = Mock(data=self.mock_product_catalog_data)
        self.mock_k8s_api.read_namespaced_secret.return_value = Mock(data=MOCK_K8S_CRED_SECRET_DATA)
        self.mock_environ = patch('shasta_install_utility_common.products.os.environ').start()
        self.mock_temporary_file = patch(
            'shasta_install_utility_common.products.NamedTemporaryFile'
        ).start().return_value.__enter__.return_value
        self.mock_check_output = patch('shasta_install_utility_common.products.subprocess.check_output').start()
        self.mock_print = patch('builtins.print').start()
        self.mock_docker = patch('shasta_install_utility_common.products.DockerApi').start().return_value
        self.mock_nexus = patch('shasta_install_utility_common.products.NexusApi').start().return_value
        self.mock_nexus.components.return_value = Mock()

    def tearDown(self):
        """Stop patches."""
        patch.stopall()

    def create_and_assert_product_catalog(self):
        """Assert the product catalog was created as expected."""
        product_catalog = ProductCatalog('mock-name', 'mock-namespace',
                                         nexus_credentials_secret_name='mock-secret',
                                         nexus_credentials_secret_namespace='mock-secret-namespace')
        self.mock_k8s_api.read_namespaced_config_map.assert_called_once_with('mock-name', 'mock-namespace')
        self.mock_k8s_api.read_namespaced_secret.assert_called_once_with('mock-secret', 'mock-secret-namespace')
        self.mock_environ.update.assert_called_once_with(
            {'NEXUS_USERNAME': b64decode(MOCK_K8S_CRED_SECRET_DATA['username']).decode(),
             'NEXUS_PASSWORD': b64decode(MOCK_K8S_CRED_SECRET_DATA['password']).decode()}
        )
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
        """Test creating a ProductCatalog when the product catalog contains invalid YAML."""
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
        expected_component_data = {'component_versions': {
            'docker': [
                {'name': 'cray/cray-cos', 'version': '1.0.0'},
                {'name': 'cray/cos-cfs-install', 'version': '1.4.0'}
            ],
            'helm': [
                {"name": "cos-config", "version": "1.0.0"},
            ]
        }
        }
        self.assertEqual(expected_component_data, actual_matching_product.data)

    def test_update_product_catalog(self):
        """Test setting a version as active in the product catalog."""
        product_catalog = self.create_and_assert_product_catalog()
        product_catalog.activate_product_entry('mock_name', 'mock_version')
        self.mock_temporary_file.write.assert_called_once_with(safe_dump({'active': True}))
        self.mock_environ.update.assert_called_with({
            'PRODUCT': 'mock_name',
            'PRODUCT_VERSION': 'mock_version',
            'CONFIG_MAP': 'mock-name',
            'CONFIG_MAP_NS': 'mock-namespace',
            'SET_ACTIVE_VERSION': 'true',
            'VALIDATE_SCHEMA': 'true',
            'YAML_CONTENT': self.mock_temporary_file.name
        })
        self.mock_check_output.assert_called_once_with(['catalog_update'])

    def test_remove_from_product_catalog(self):
        """Test removing a version from the product catalog."""
        product_catalog = self.create_and_assert_product_catalog()
        product_catalog.remove_product_entry('mock_name', 'mock_version')
        self.mock_environ.update.assert_called_with({
            'PRODUCT': 'mock_name',
            'PRODUCT_VERSION': 'mock_version',
            'CONFIG_MAP': 'mock-name',
            'CONFIG_MAP_NS': 'mock-namespace',
            'VALIDATE_SCHEMA': 'true'
        })
        self.mock_check_output.assert_called_once_with(['catalog_delete'])

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
        with patch('shasta_install_utility_common.products.uninstall_docker_image') as mock_uninstall_docker_image:
            product_catalog.remove_product_docker_images('sat', '2.0.0')
            mock_uninstall_docker_image.assert_has_calls([
                call('cray/cray-sat', '1.0.0', self.mock_docker),
                call('cray/sat-cfs-install', '1.4.0', self.mock_docker)
            ])

    def test_partial_remove_docker_images(self):
        """Test a removal of docker images when an image is shared."""
        product_catalog = self.create_and_assert_product_catalog()
        with patch('shasta_install_utility_common.products.uninstall_docker_image') as mock_uninstall_docker_image:
            product_catalog.remove_product_docker_images('cos', '2.0.0')
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
        with patch('shasta_install_utility_common.products.uninstall_docker_image') as mock_uninstall_docker_image:
            product_catalog.remove_product_docker_images('other_product', '2.0.0')
            mock_uninstall_docker_image.assert_not_called()
            self.mock_print.assert_called_once_with(
                'Not removing Docker image cray/cray-sat:1.0.1 used '
                'by the following other product versions: sat-2.0.1'
            )

    def test_remove_docker_images_errors(self):
        """Test uninstalling Docker images when an error occurred."""
        product_catalog = self.create_and_assert_product_catalog()
        uninstall_exception = ProductInstallException('fail')
        expected_regex = 'One or more errors occurred removing Docker images for sat 2.0.0.'
        with patch('shasta_install_utility_common.products.uninstall_docker_image', side_effect=uninstall_exception):
            with self.assertRaisesRegex(ProductInstallException, expected_regex):
                product_catalog.remove_product_docker_images('sat', '2.0.0')
        self.mock_print.assert_has_calls([
            call(f'Failed to remove cray/cray-sat:1.0.0: {uninstall_exception}'),
            call(f'Failed to remove cray/sat-cfs-install:1.4.0: {uninstall_exception}')
        ])
    
    @patch('shasta_install_utility_common.products.uninstall_nexus_helm_chart')
    @patch('shasta_install_utility_common.products.uninstall_k8_helm_charts')
    def test_remove_helm_charts(self, mock_uninstall_k8_helm_chart, mock_uninstall_nexus_helm_chart):
        """Test for removing helm charts from the product catalog."""
        product_catalog = self.create_and_assert_product_catalog()
        updated_config_map = copy.deepcopy(MOCK_PRODUCT_CATALOG_DATA_HELM_TESTS)
        mock_uninstall_k8_helm_chart.return_value = V1ConfigMap(data=updated_config_map)
        self.mock_nexus.components.list.return_value = MOCK_K8S_HELM_CHARTS_COMPONENTS
        product_catalog.remove_helm_charts("cos", "2.0.0")
        mock_uninstall_nexus_helm_chart.assert_called_once_with("cos-config", "1.0.0", "id1", self.mock_nexus)
        mock_uninstall_k8_helm_chart.assert_called_once_with("cos", "2.0.0", [("cos-config", "1.0.0", "id1")], self.mock_k8s_api)
        self.mock_temporary_file.write.assert_called_once_with(safe_dump(updated_config_map['cos']['2.0.0']))
        self.mock_environ.update.assert_called_with({
            'PRODUCT': 'cos',
            'PRODUCT_VERSION': '2.0.0',
            'CONFIG_MAP': 'mock-name',
            'CONFIG_MAP_NS': 'mock-namespace',
            'SET_ACTIVE_VERSION': 'true',
            'VALIDATE_SCHEMA': 'true',
            'YAML_CONTENT': self.mock_temporary_file.name
        })
        
    @patch('shasta_install_utility_common.products.uninstall_nexus_helm_chart')
    @patch('shasta_install_utility_common.products.uninstall_k8_helm_charts')
    def test_remove_helm_charts(self, mock_uninstall_k8_helm_chart, mock_uninstall_nexus_helm_chart):
        """Test for removing helm charts from the product catalog."""
        product_catalog = self.create_and_assert_product_catalog()
        updated_config_map = copy.deepcopy(MOCK_PRODUCT_CATALOG_DATA_HELM_TESTS)
        mock_uninstall_k8_helm_chart.return_value = V1ConfigMap(data=updated_config_map)
        self.mock_nexus.components.list.return_value = []
        product_catalog.remove_helm_charts("cos", "2.0.0")
        self.mock_print.assert_called_once_with("No helm charts found to remove for cos:2.0.0")

    def test_activate_product_hosted_repos(self):
        """Test activate_product_hosted_repos."""
        product_catalog = self.create_and_assert_product_catalog()
        with patch.object(InstalledProductVersion, 'activate_hosted_repos_in_group') as mock_activate:
            product_catalog.activate_product_hosted_repos('sat', '2.0.0')
        mock_activate.assert_called_once_with(self.mock_nexus)

    def test_uninstall_product_hosted_repos(self):
        """Test uninstall_product_hosted_repos."""
        product_catalog = self.create_and_assert_product_catalog()
        with patch.object(InstalledProductVersion, 'uninstall_hosted_repos') as mock_uninstall:
            product_catalog.uninstall_product_hosted_repos('sat', '2.0.0')
        mock_uninstall.assert_called_once_with(self.mock_nexus)


class TestUninstallDockerImage(unittest.TestCase):
    """Tests for uninstall_docker_image."""

    def setUp(self):
        """Set up mocks."""
        self.mock_docker_api = Mock()
        self.mock_print = patch('builtins.print').start()

    def tearDown(self):
        """Stop patches."""
        patch.stopall()

    def test_uninstall_docker_image(self):
        """Test uninstalling Docker images for an InstalledProductVersion."""
        uninstall_docker_image('foo', 'bar', self.mock_docker_api)
        self.mock_docker_api.delete_image.assert_called_once_with('foo', 'bar')

    def test_uninstall_docker_image_not_found(self):
        """Test uninstalling Docker images when image is not found is not an error."""
        self.mock_docker_api.delete_image.side_effect = HTTPError(
            url='http://nexus', code=404, msg='Not found', hdrs=None, fp=None
        )
        uninstall_docker_image('foo', 'bar', self.mock_docker_api)
        self.mock_docker_api.delete_image.assert_called_once_with('foo', 'bar')
        self.mock_print.assert_called_once_with('foo:bar has already been removed.')

    def test_uninstall_docker_other_error(self):
        """Test uninstalling Docker images when a non-404 error occurs is an error."""
        http_error = self.mock_docker_api.delete_image.side_effect = HTTPError(
            url='http://nexus', code=503, msg='Nexus problems', hdrs=None, fp=None
        )
        expected_regex = f'Failed to remove image foo:bar: {http_error}'
        with self.assertRaisesRegex(ProductInstallException, expected_regex):
            uninstall_docker_image('foo', 'bar', self.mock_docker_api)
        self.mock_docker_api.delete_image.assert_called_once_with('foo', 'bar')
        
class TestUninstallK8HelmCharts(unittest.TestCase):
    """Tests for uninstall_k8_helm_charts"""
    
    def setUp(self) -> None:
        self.mock_k8s_client = Mock()
        self.product_name = "foo-product"
        
    def tearDown(self) -> None:
        patch.stopall()
        
    def test_uninstall_k8_helm_charts(self):
        data = {
            "foo-product": "1.0.0:\n  component_versions:\n    docker:\n    - name: arti.hpc.amslabs.hpecorp.net/cray-product-catalog-update\n      version: 1.3.2\n    - name: arti.hpc.amslabs.hpecorp.net/cray-cos-config\n      version: 1.6.26\n    - name: arti.hpc.amslabs.hpecorp.net/cray-cos-image-sle15sp4\n      version: 2.1.18\n    - name: cray/cray-cps-pm\n      version: 2.8.6\n    - name: cray/cray-cps-broker\n      version: 2.11.10\n    - name: cray/cos-install-utility\n      version: 1.3.2\n    - name: cray/cray-nmdv2\n      version: 2.10.10\n    - name: cray/cray-cos-config-service\n      version: 1.0.3\n    - name: cray/cray-cps-cm\n      version: 2.8.6\n    helm:\n    - name: foo-chart\n      version: 0.0.1\n    - name: cray-cps\n      version: 1.10.10\n    - name: nmdv2-service\n      version: 1.10.10\n    - name: cos-sle15sp4-artifacts\n      version: 2.1.18\n    - name: cos-config-service\n      version: 1.0.3\n    manifests:\n    - config-data/argo/loftsman/cos/2.5.99/manifests/cos-services.yaml\n    repositories:\n    - name: cos-2.5.99-sle-15sp4\n      type: hosted\n    - members:\n      - cos-2.5.99-sle-15sp4\n      name: cos-2.5-sle-15sp4\n      type: group\n    - name: cos-2.5.99-net-sle-15sp4-shs-2.0\n      type: hosted\n    - members:\n      - cos-2.5.99-net-sle-15sp4-shs-2.0\n      name: cos-2.5-net-sle-15sp4-shs-2.0\n      type: group\n    - name: cos-2.5.99-sle-15sp4-compute\n      type: hosted\n    - members:\n      - cos-2.5.99-sle-15sp4-compute\n      name: cos-2.5-sle-15sp4-compute\n      type: group\n    - name: cos-2.5.99-net-sle-15sp4-compute-shs-2.0\n      type: hosted\n    - members:\n      - cos-2.5.99-net-sle-15sp4-compute-shs-2.0\n      name: cos-2.5-net-sle-15sp4-compute-shs-2.0\n      type: group\n  configuration:\n    clone_url: https://vcs.cmn.mug.hpc.amslabs.hpecorp.net/vcs/cray/cos-config-management.git\n    commit: b1d15f5f5216a3391adcba47afb9ab80f3109795\n    import_branch: cray/cos/2.5.99\n    import_date: 2023-03-24 10:13:09.580643\n    ssh_url: git@vcs.cmn.mug.hpc.amslabs.hpecorp.net:cray/cos-config-management.git\n  images: {}\n  recipes:\n    cray-shasta-compute-sles15sp4.noarch-2.5.30:\n      id: 3b1cb85d-c1fb-4a4b-9b7f-7a06a9fe2411\n",
        }
        expected_data = {
            "foo-product": "1.0.0:\n  component_versions:\n    docker:\n    - name: arti.hpc.amslabs.hpecorp.net/cray-product-catalog-update\n      version: 1.3.2\n    - name: arti.hpc.amslabs.hpecorp.net/cray-cos-config\n      version: 1.6.26\n    - name: arti.hpc.amslabs.hpecorp.net/cray-cos-image-sle15sp4\n      version: 2.1.18\n    - name: cray/cray-cps-pm\n      version: 2.8.6\n    - name: cray/cray-cps-broker\n      version: 2.11.10\n    - name: cray/cos-install-utility\n      version: 1.3.2\n    - name: cray/cray-nmdv2\n      version: 2.10.10\n    - name: cray/cray-cos-config-service\n      version: 1.0.3\n    - name: cray/cray-cps-cm\n      version: 2.8.6\n    helm:\n    - name: cray-cps\n      version: 1.10.10\n    - name: nmdv2-service\n      version: 1.10.10\n    - name: cos-sle15sp4-artifacts\n      version: 2.1.18\n    - name: cos-config-service\n      version: 1.0.3\n    manifests:\n    - config-data/argo/loftsman/cos/2.5.99/manifests/cos-services.yaml\n    repositories:\n    - name: cos-2.5.99-sle-15sp4\n      type: hosted\n    - members:\n      - cos-2.5.99-sle-15sp4\n      name: cos-2.5-sle-15sp4\n      type: group\n    - name: cos-2.5.99-net-sle-15sp4-shs-2.0\n      type: hosted\n    - members:\n      - cos-2.5.99-net-sle-15sp4-shs-2.0\n      name: cos-2.5-net-sle-15sp4-shs-2.0\n      type: group\n    - name: cos-2.5.99-sle-15sp4-compute\n      type: hosted\n    - members:\n      - cos-2.5.99-sle-15sp4-compute\n      name: cos-2.5-sle-15sp4-compute\n      type: group\n    - name: cos-2.5.99-net-sle-15sp4-compute-shs-2.0\n      type: hosted\n    - members:\n      - cos-2.5.99-net-sle-15sp4-compute-shs-2.0\n      name: cos-2.5-net-sle-15sp4-compute-shs-2.0\n      type: group\n  configuration:\n    clone_url: https://vcs.cmn.mug.hpc.amslabs.hpecorp.net/vcs/cray/cos-config-management.git\n    commit: b1d15f5f5216a3391adcba47afb9ab80f3109795\n    import_branch: cray/cos/2.5.99\n    import_date: 2023-03-24 10:13:09.580643\n    ssh_url: git@vcs.cmn.mug.hpc.amslabs.hpecorp.net:cray/cos-config-management.git\n  images: {}\n  recipes:\n    cray-shasta-compute-sles15sp4.noarch-2.5.30:\n      id: 3b1cb85d-c1fb-4a4b-9b7f-7a06a9fe2411\n",
        }
        removed_helm_data = data
        removed_helm_data[self.product_name] = expected_data[self.product_name]
        expected_config_map_data = V1ConfigMap(data=removed_helm_data)

        self.mock_k8s_client.read_namespaced_config_map.return_value = V1ConfigMap(data=data)
        updated_config_map = uninstall_k8_helm_charts(self.product_name, '1.0.0', [
                                 ('foo-chart', '0.0.1', 'foo-id')], self.mock_k8s_client)
        self.mock_k8s_client.read_namespaced_config_map.assert_called_with(
            PRODUCT_CATALOG_CONFIG_MAP_NAME, PRODUCT_CATALOG_CONFIG_MAP_NAMESPACE)
        
        assert updated_config_map.data == expected_config_map_data.data

    def test_uninstall_k8_helm_charts_no_charts(self):
        with self.assertRaises(ProductInstallException,
                               msg="No charts to delete from cray-product-catalog ConfigMap."):
            uninstall_k8_helm_charts(self.product_name, '1.0.0', [], self.mock_k8s_client)

    def test_uninstall_k8_helm_charts_max_retry(self):
        self.mock_k8s_client.read_namespaced_config_map.side_effect = MaxRetryError(url=None, pool=None)
        with self.assertRaises(ProductInstallException,
                               msg=f"Unable to connect to Kubernetes to read {PRODUCT_CATALOG_CONFIG_MAP_NAME}/foo-product ConfigMap:"):
            uninstall_k8_helm_charts(self.product_name, '1.0.0', [('foo-chart', '0.0.1')], self.mock_k8s_client)

    def test_uninstall_k8_helm_charts_api_exception(self):
        self.mock_k8s_client.read_namespaced_config_map.side_effect = ApiException()
        with self.assertRaises(ProductInstallException,
                               msg=f"Error reading {PRODUCT_CATALOG_CONFIG_MAP_NAME}/{self.product_name} ConfigMap:"):
            uninstall_k8_helm_charts(self.product_name, '1.0.0', [('foo-chart', '0.0.1')], self.mock_k8s_client)

    def test_uninstall_k8_helm_charts_no_data(self):
        self.mock_k8s_client.read_namespaced_config_map.return_value = V1ConfigMap(data={})
        with self.assertRaises(ProductInstallException,
                               msg=f"No data found in {PRODUCT_CATALOG_CONFIG_MAP_NAME}/{self.product_name} ConfigMap."):
            uninstall_k8_helm_charts(self.product_name, '1.0.0', [('foo-chart', '0.0.1')], self.mock_k8s_client)


class TestUninstallNexusHelmChart(unittest.TestCase):
    """Tests for uninstall_nexus_helm_chart."""

    def setUp(self) -> None:
        self.mock_nexus_api = Mock()
        self.mock_nexus_api.client = Mock()
        self.mock_nexus_api.client.base_url = "http://nexus"
        self.mock_nexus_api.components = Mock()
        self.mock_print: MagicMock | AsyncMock = patch('builtins.print').start()

    def tearDown(self) -> None:
        patch.stopall()
        
    def test_uninstall_nexus_helm_chart(self):
        """Tests for uninstall_nexus_helm_chart for an InstalledProductVersion."""
        uninstall_nexus_helm_chart('foo', '1.2.3', 'foo-id', self.mock_nexus_api)
        self.mock_nexus_api.components.delete.assert_called_once_with('foo-id')
        
    def test_uninstall_nexus_helm_chart_not_found(self):
        """Tests for uninstall_nexus_helm_chart for 404 error."""
        self.mock_nexus_api.components.delete.side_effect = HTTPError(
            "url", 404, "foo msg", None, None)
        uninstall_nexus_helm_chart('foo', '1.2.3', 'foo-id', self.mock_nexus_api)
        self.mock_print.assert_called_once_with(
        "Helm chart foo:1.2.3 has already been removed.")
        
    def test_uninstall_nexus_helm_chart_non_200(self):
        """Tests for uninstall_nexus_helm_chart for non-200 error."""
        self.mock_nexus_api.components.delete.side_effect = HTTPError(
            "url", 500, "foo msg", None, None)
        with self.assertRaises(ProductInstallException, msg='Failed to remove helm chart foo:1.2.3: string response'):
            uninstall_nexus_helm_chart('foo', '1.2.3', 'foo-id', self.mock_nexus_api)

class TestInstalledProductVersion(unittest.TestCase):
    """Tests for the InstalledProductVersion class."""
    def setUp(self):
        """Set up mocks."""
        self.installed_product_version = InstalledProductVersion(
            'sat', '2.0.1', SAT_VERSIONS['2.0.1'], None
        )
        self.mock_nexus_api = Mock()
        self.mock_group_members = ['sat-3.0.0-sle-15sp3', 'sat-2.2.0-sle-15sp3', 'sat-1.0.1-sle-15sp3']
        self.mock_group_repo = Mock()
        self.mock_group_repo.group.member_names = self.mock_group_members
        # This is slightly incorrect as NexusApi.repos.list may also return a
        # hosted repo, but good enough for the test.
        self.mock_nexus_api.repos.list.return_value = [self.mock_group_repo]
        self.mock_print = patch('builtins.print').start()

    def tearDown(self):
        """Stop patches."""
        patch.stopall()

    def test_docker_images(self):
        """Test getting the Docker images."""
        expected_docker_image_versions = [('cray/cray-sat', '1.0.1'),
                                          ('cray/sat-other-image', '1.4.0')]
        self.assertEqual(
            expected_docker_image_versions, self.installed_product_version.docker_images
        )

    def test_legacy_docker_images(self):
        """Test getting the Docker images from an 'old'-style product catalog entry."""
        legacy_installed_product_version = InstalledProductVersion(
            'sat', '1.0.1', {'component_versions': {'sat': '1.0.0'}}, None
        )
        expected_docker_image_versions = [('cray/cray-sat', '1.0.0')]
        self.assertEqual(
            expected_docker_image_versions, legacy_installed_product_version.docker_images
        )

    def test_no_docker_images(self):
        """Test a product that has an empty dictionary under the 'docker' key returns an empty dictionary."""
        product_with_no_docker_images = InstalledProductVersion(
            'sat', '0.9.9', {'component_versions': {'docker': {}}}, None
        )
        self.assertEqual(product_with_no_docker_images.docker_images, [])

    def test_no_docker_images_null(self):
        """Test a product that has None under the 'docker' key returns an empty dictionary."""
        product_with_no_docker_images = InstalledProductVersion(
            'sat', '0.9.9', {'component_versions': {'docker': None}}, None
        )
        self.assertEqual(product_with_no_docker_images.docker_images, [])

    def test_no_docker_images_empty_list(self):
        """Test a product that has an empty list under the 'docker' key returns an empty dictionary."""
        product_with_no_docker_images = InstalledProductVersion(
            'sat', '0.9.9', {'component_versions': {'docker': []}}, None
        )
        self.assertEqual(product_with_no_docker_images.docker_images, [])

    def test_str(self):
        """Test the string representation of InstalledProductVersion."""
        expected_str = 'sat-2.0.1'
        self.assertEqual(
            expected_str, str(self.installed_product_version)
        )

    def test_group_repos(self):
        """Test getting group repo data for an InstalledProductVersion."""
        expected_group_repos = [{'members': ['sat-2.0.1-sle-15sp2'], 'name': 'sat-sle-15sp2', 'type': 'group'}]
        self.assertEqual(
            expected_group_repos, self.installed_product_version.group_repositories
        )

    def test_hosted_repos(self):
        """Test getting hosted repo names for an InstalledProductVersion."""
        expected_hosted_repo_names = {'sat-2.0.1-sle-15sp2'}
        self.assertEqual(
            expected_hosted_repo_names, self.installed_product_version.hosted_repository_names
        )

    def test_hosted_repos_without_members(self):
        """Test getting hosted repo names that are listed only as hosted repos but not a member of a group."""
        sat_version_data = copy.deepcopy(SAT_VERSIONS['2.0.0'])
        sat_version_data['component_versions']['repositories'] = [
            {'name': 'my-hosted-repo', 'type': 'hosted'}
        ]
        ipv = InstalledProductVersion('sat', '2.0.0', sat_version_data, None)
        expected_hosted_repo_names = {'my-hosted-repo'}
        self.assertEqual(ipv.hosted_repository_names, expected_hosted_repo_names)

    def test_hosted_repos_only_members(self):
        """Test getting hosted repo names that are not listed except as a member of a group."""
        sat_version_data = copy.deepcopy(SAT_VERSIONS['2.0.0'])
        sat_version_data['component_versions']['repositories'] = [
            {'name': 'my-group-repo', 'type': 'group', 'members': ['my-hosted-repo']}
        ]
        ipv = InstalledProductVersion('sat', '2.0.0', sat_version_data, None)
        expected_hosted_repo_names = {'my-hosted-repo'}
        self.assertEqual(ipv.hosted_repository_names, expected_hosted_repo_names)

    def test_uninstall_hosted_repos(self):
        """Test uninstalling hosted repos for an InstalledProductVersion."""
        self.installed_product_version.uninstall_hosted_repos(self.mock_nexus_api)
        self.mock_nexus_api.repos.delete.assert_called_once_with('sat-2.0.1-sle-15sp2')

    def test_uninstall_hosted_repos_not_found(self):
        """Test uninstalling hosted repos when repos are not found is not an error."""
        self.mock_nexus_api.repos.delete.side_effect = HTTPError(
            url='http://nexus', code=404, msg='Not found', hdrs=None, fp=None
        )
        self.installed_product_version.uninstall_hosted_repos(self.mock_nexus_api)
        self.mock_nexus_api.repos.delete.assert_called_once_with('sat-2.0.1-sle-15sp2')
        self.mock_print.assert_called_once_with('sat-2.0.1-sle-15sp2 has already been removed.')

    def test_uninstall_hosted_repos_other_error(self):
        """Test uninstalling hosted repos when a non-404 HTTP error occurs is an error."""
        http_error = self.mock_nexus_api.repos.delete.side_effect = HTTPError(
            url='http://nexus', code=503, msg='Nexus problems', hdrs=None, fp=None
        )
        expected_regex = 'One or more errors occurred uninstalling repositories for sat 2.0.1'
        with self.assertRaisesRegex(ProductInstallException, expected_regex):
            self.installed_product_version.uninstall_hosted_repos(self.mock_nexus_api)
        self.mock_print.assert_called_once_with(
            f'Failed to remove hosted repository sat-2.0.1-sle-15sp2: {http_error}'
        )
        self.mock_nexus_api.repos.delete.assert_called_once_with('sat-2.0.1-sle-15sp2')

    def test_activate_hosted_repos(self):
        """Test activating a product version's hosted repositories."""
        self.installed_product_version.activate_hosted_repos_in_group(self.mock_nexus_api)
        self.mock_nexus_api.repos.raw_group.update.assert_called_once_with(
            self.mock_group_repo.name,
            self.mock_group_repo.online,
            self.mock_group_repo.storage.blobstore_name,
            self.mock_group_repo.storage.strict_content_type_validation,
            member_names=['sat-2.0.1-sle-15sp2']
        )

    def test_activate_hosted_repos_error(self):
        """Test activating a product version's hosted repositories when an error occurs."""
        http_error = self.mock_nexus_api.repos.raw_group.update.side_effect = HTTPError(
            url='http://nexus', code=503, msg='Nexus problems', hdrs=None, fp=None
        )
        expected_regex = 'One or more errors occurred activating repositories for sat 2.0.1.'
        with self.assertRaisesRegex(ProductInstallException, expected_regex):
            self.installed_product_version.activate_hosted_repos_in_group(self.mock_nexus_api)
        self.mock_nexus_api.repos.raw_group.update.assert_called_once_with(
            self.mock_group_repo.name,
            self.mock_group_repo.online,
            self.mock_group_repo.storage.blobstore_name,
            self.mock_group_repo.storage.strict_content_type_validation,
            member_names=['sat-2.0.1-sle-15sp2']
        )
        self.mock_print.assert_called_once_with(
            f'Failed to update group repository {self.mock_group_repo.name} '
            f'with member repositories: [sat-2.0.1-sle-15sp2]. Error: {http_error}'
        )


if __name__ == '__main__':
    unittest.main()
