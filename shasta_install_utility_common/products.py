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
Contains the ProductCatalog and InstalledProductVersion classes.
"""

import os
import subprocess
import warnings
from base64 import b64decode
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.error import HTTPError
from urllib.request import Request

from cray_product_catalog.schema.validate import validate
from jsonschema.exceptions import ValidationError
from kubernetes.client import CoreV1Api, V1ConfigMap
from kubernetes.client.rest import ApiException
from kubernetes.config import ConfigException, load_kube_config
from nexusctl import DockerApi, DockerClient, NexusApi, NexusClient
from nexusctl.common import (DEFAULT_DOCKER_REGISTRY_API_BASE_URL,
                             DEFAULT_NEXUS_API_BASE_URL)
from nexusctl.nexus.models import RepoListGroupEntry, RepoListHostedEntry
from nexusctl.nexus.models.component_xo import PageComponentXO
from urllib3.exceptions import MaxRetryError
from yaml import YAMLError, YAMLLoadWarning, safe_dump, safe_load

from shasta_install_utility_common.constants import (
    COMPONENT_DOCKER_KEY, COMPONENT_HELM_KEY, COMPONENT_REPOS_KEY,
    COMPONENT_VERSIONS_PRODUCT_MAP_KEY, NEXUS_CREDENTIALS_SECRET_NAME,
    NEXUS_CREDENTIALS_SECRET_NAMESPACE, PRODUCT_CATALOG_CONFIG_MAP_NAME,
    PRODUCT_CATALOG_CONFIG_MAP_NAMESPACE)

Name = str
Version = str
NexusComponentId = str
HelmChartDict = Dict[Name, Version]
HelmChartTuples = List[Tuple[Name, Version]]
NexusHelmChartTuples = List[Tuple[Name, Version, NexusComponentId]]


def uninstall_docker_image(docker_image_name, docker_image_version, docker_api):
    """Remove a Docker image.

    It is not recommended to call this function directly, instead use
    ProductCatalog.uninstall_product_docker_images to check that the image
    is not in use by another product.

    Args:
        docker_image_name (str): The name of the Docker image to uninstall.
        docker_image_version (str): The version of the Docker image to uninstall.
        docker_api (DockerApi): The nexusctl Docker API to interface with
            the Docker registry.

    Returns:
        None

    Raises:
        ProductInstallException: If an error occurred removing the image.
    """
    docker_image_short_name = f'{docker_image_name}:{docker_image_version}'
    try:
        docker_api.delete_image(
            docker_image_name, docker_image_version
        )
        print(f'Removed Docker image {docker_image_short_name}')
    except HTTPError as err:
        if err.code == 404:
            print(f'{docker_image_short_name} has already been removed.')
        else:
            raise ProductInstallException(
                f'Failed to remove image {docker_image_short_name}: {err}'
            )


def uninstall_nexus_helm_chart(name: Name, version: Version, id: NexusComponentId, nexus_api: NexusApi) -> None:
    """
    Removes a specified helm chart from the the nexus hosted chart repository

    Args:
        name (str): The name of the helm chart to be removed from nexus.
        version (str): The version of the helm chart to be removed from the nexus.
        id (str): The component id of the helm chart to be removed from the nexus.
        nexus_api (NexusApi): The nexusctl Nexus API to interface with the repository.

    Raises:
        ProductInstallException: If an error is encountered during deletion.
    """
    helm_chart_short_name: str = f"{name}:{version}"
    try:
        nexus_api.components.delete(id)
    except HTTPError as err:
        if err.code == 404:
            print(
                f"Helm chart {helm_chart_short_name} has already been removed.")
        else:
            raise ProductInstallException(
                f"Failed to remove helm chart {helm_chart_short_name} from nexus")


def uninstall_k8_helm_charts(product_name: str,
                             product_version: str,
                             charts_deleted_nexus: NexusHelmChartTuples,
                             k8s_client: CoreV1Api) -> V1ConfigMap:
    """
    Removes all charts deleted from nexus to propogate changes to cluster configmaps using cray-product-catalog
    catalog_update.py. This assures that both charts will be delete in Nexus and then ConfigMaps.

    Args:
        charts_deleted_from_nexus (HelmChartTuples): The list of charts deleted from Nexus.
        k8s_client (CoreV1Api): Kubernetes client to interface with cluster with.

    Raises:
        ProductInstallException: If the k8s_client can not connect to the cluster or data is not found.
        ApiException: If unknown error reading the data from the k8s_client.
    """
    if len(charts_deleted_nexus) == 0:
        raise ProductInstallException(
            f"No charts to delete from cray-product-catalog ConfigMap.")

    try:
        config_map: V1ConfigMap = k8s_client.read_namespaced_config_map(
            PRODUCT_CATALOG_CONFIG_MAP_NAME, PRODUCT_CATALOG_CONFIG_MAP_NAMESPACE)  # type: ignore
    except MaxRetryError as err:
        raise ProductInstallException(
            f'Unable to connect to Kubernetes to read {PRODUCT_CATALOG_CONFIG_MAP_NAME}/{product_name} ConfigMap: {err}'
        )
    except ApiException as err:
        raise ProductInstallException(
            f'Error reading {PRODUCT_CATALOG_CONFIG_MAP_NAME}/{product_name} ConfigMap: {err.reason}'
        )
    if config_map.data is None:
        raise ProductInstallException(
            f'No data found in {PRODUCT_CATALOG_CONFIG_MAP_NAME}/{product_name} ConfigMap.'
        )

    # Get product data
    try:
        config_map.data[product_name]
    except KeyError:
        raise ProductInstallException(
            f'No ConfigMap data found for {product_name}'
        )

    # Load the yaml data from the ConfigMap
    product_data: dict = safe_load(config_map.data[product_name])
    try:
        product_charts: list[HelmChartDict] = product_data[product_version][COMPONENT_VERSIONS_PRODUCT_MAP_KEY][COMPONENT_HELM_KEY]
    except KeyError:
        raise ProductInstallException(
            f"There are no helm charts located in the product catalog configmap for '{product_name}:{product_version}'")

    # Delete from the local configmap (NxM in best case N^2 in worst) have to find chart name in list of dictionaries.
    for chart in charts_deleted_nexus:
        name, version, component_id = chart
        print(f"Attempting to delete chart {name}:{version}:{component_id}")
        for idx, chart_dict in enumerate(product_charts):
            if name == chart_dict['name']:
                del product_charts[idx]
                break

    # set new chart data
    product_data[product_version][COMPONENT_VERSIONS_PRODUCT_MAP_KEY][COMPONENT_HELM_KEY] = product_charts
    config_map.data[product_name] = product_data
    return config_map


class ProductInstallException(Exception):
    """An error occurred reading or manipulating product installs."""
    pass


class ProductCatalog:
    """A collection of installed product versions.

    Attributes:
        name: The product catalog Kubernetes config map name.
        namespace: The product catalog Kubernetes config map namespace.
        products ([InstalledProductVersion]): A list of installed product
            versions.
    """
    @staticmethod
    def _get_k8s_api():
        """Load a Kubernetes CoreV1Api and return it.

        Returns:
            CoreV1Api: The Kubernetes API.

        Raises:
            ProductInstallException: if there was an error loading the
                Kubernetes configuration.
        """
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=YAMLLoadWarning)
                load_kube_config()
            return CoreV1Api()
        except ConfigException as err:
            raise ProductInstallException(f'Unable to load kubernetes configuration: {err}.')

    def __init__(self, name=PRODUCT_CATALOG_CONFIG_MAP_NAME, namespace=PRODUCT_CATALOG_CONFIG_MAP_NAMESPACE,
                 nexus_url=DEFAULT_NEXUS_API_BASE_URL, docker_url=DEFAULT_DOCKER_REGISTRY_API_BASE_URL,
                 nexus_credentials_secret_name=NEXUS_CREDENTIALS_SECRET_NAME,
                 nexus_credentials_secret_namespace=NEXUS_CREDENTIALS_SECRET_NAMESPACE):
        """Create the ProductCatalog object.

        Args:
            name (str): The name of the product catalog Kubernetes config map.
            namespace (str): The namespace of the product catalog Kubernetes
                config map.
            nexus_url (str): The URL of the Nexus repository API.
            docker_url (str): The URL of the Docker repository API.
            nexus_credentials_secret_name (str): The name of a Kubernetes secret
                containing HTTP credentials to access Nexus.
            nexus_credentials_secret_namespace (str): The namespace of a
                Kubernetes secret containing HTTP credentials to access Nexus.

        Raises:
            ProductInstallException: if reading the config map failed.
        """
        self.name = name
        self.namespace = namespace
        self.k8s_client = self._get_k8s_api()
        self._update_environment_with_nexus_credentials(
            nexus_credentials_secret_name, nexus_credentials_secret_namespace
        )

        self.docker_api = DockerApi(DockerClient(docker_url))
        self.nexus_api = NexusApi(NexusClient(nexus_url))
        self.helm_charts_deleted_nexus: NexusHelmChartTuples = list()
        try:
            config_map = self.k8s_client.read_namespaced_config_map(
                name, namespace)
        except MaxRetryError as err:
            raise ProductInstallException(
                f'Unable to connect to Kubernetes to read {namespace}/{name} ConfigMap: {err}'
            )
        except ApiException as err:
            # The full string representation of ApiException is very long, so just log err.reason.
            raise ProductInstallException(
                f'Error reading {namespace}/{name} ConfigMap: {err.reason}'
            )

        if config_map.data is None:
            raise ProductInstallException(
                f'No data found in {namespace}/{name} ConfigMap.'
            )

        # Get nexus charts data, since the entire list must be acquired only make this call once.
        # nexus delete API requires a component id
        # Each InstalledProduct must have the all the chart components to find the respective charts.
        try:
            nexus_charts = self.nexus_api.components.list("charts")
        except HTTPError as err:
            raise ProductInstallException(
                f"Failed to load Nexus components for 'charts' repository: {err}"
            )

        try:
            self.products = [
                InstalledProductVersion(
                    product_name, product_version, product_version_data, nexus_charts)
                for product_name, product_versions in config_map.data.items()
                for product_version, product_version_data in safe_load(product_versions).items()
            ]
        except YAMLError as err:
            raise ProductInstallException(
                f'Failed to load ConfigMap data: {err}'
            )

        invalid_products = [
            str(p) for p in self.products if not p.is_valid
        ]
        if invalid_products:
            print(f'The following products have product catalog data that '
                  f'is not understood by the install utility: {", ".join(invalid_products)}')

        self.products = [
            p for p in self.products if p.is_valid
        ]

    def _update_environment_with_nexus_credentials(self, secret_name, secret_namespace):
        """Get the credentials for Nexus HTTP API access from a Kubernetes secret.

        Nexusctl expects these to be set as environment variables. If they
        cannot be obtained from a k8s secret, then print a warning and return.

        Args:
            secret_name (str): The name of the secret.
            secret_namespace (str): The namespace of the secret.

        Returns:
            None. Updates os.environ as is expected by Nexusctl.
        """
        try:
            secret = self.k8s_client.read_namespaced_secret(
                secret_name, secret_namespace
            )
        except (MaxRetryError, ApiException):
            print(f'WARNING: unable to read Kubernetes secret {secret_namespace}/{secret_name}')
            return

        if secret.data is None:
            print(f'WARNING: unable to read Kubernetes secret {secret_namespace}/{secret_name}')
            return

        os.environ.update({
            'NEXUS_USERNAME': b64decode(secret.data['username']).decode(),
            'NEXUS_PASSWORD': b64decode(secret.data['password']).decode()
        })

    def get_product(self, name, version):
        """Get the InstalledProductVersion matching the given name/version.

        Args:
            name (str): The product name.
            version (str): The product version.

        Returns:
            An InstalledProductVersion with the given name and version.

        Raises:
            ProductInstallException: If there is more than one matching
                InstalledProductVersion, or if there are none.
        """
        matching_products = [
            product for product in self.products
            if product.name == name and product.version == version
        ]
        if not matching_products:
            raise ProductInstallException(
                f'No installed products with name {name} and version {version}.'
            )
        elif len(matching_products) > 1:
            raise ProductInstallException(
                f'Multiple installed products with name {name} and version {version}.'
            )

        return matching_products[0]

    def remove_helm_charts(self, name: str, version: str) -> None:
        """
        Remove a product's Helm charts.
        
        This function will remove helm charts that are tied to a certain product
        through the kubernetes api and nexus storage. This also tracks which
        charts are successfully removed from nexus.

        Args:
            name (str): The name of the product for which to remove helm charts.
            version (str): The version of the product for which to remove helm charts.
        """
        product: InstalledProductVersion = self.get_product(name, version)
        k8s_charts: Optional[NexusHelmChartTuples] = product.get_helm_chart_nexus_component_ids()

        if not k8s_charts:
            print(f"No helm charts found to remove for {name}:{version}")
            return

        for chart in k8s_charts:
            chart_name, chart_version, component_id = chart
            try:
                uninstall_nexus_helm_chart(
                    chart_name, chart_version, component_id, self.nexus_api)
                self.helm_charts_deleted_nexus.append(chart)
            except ProductInstallException as err:
                print(
                    f'Failed to remove chart {chart_name}:{chart_version} from {name}:{version}: {err}')

        # Remove from K8s configmap.
        try:
            updated_config_map: V1ConfigMap = uninstall_k8_helm_charts(name,
                                                                       version,
                                                                       self.helm_charts_deleted_nexus,
                                                                       self.k8s_client)
        except ProductInstallException as err:
            print(f'Failed to remove helm charts from the ConfigMap: {err}')
            raise err

        # Update the catalog ConfigMap with cray-product-catalog (catalog_update.py)
        try:
            self.update_product_data(name, version, updated_config_map.data[name][version])
        except ProductInstallException as err:
            print(f'Failed to update helm charts in the ConfigMap: {err}')
            raise err

    def remove_product_docker_images(self, name, version):
        """Remove a product's Docker images.

        This function will only remove images that are not used by another
        product in the catalog. For images that are used by another

        Args:
            name (str): The name of the product for which to remove docker images.
            version (str): The version of the product for which to remove docker images.

        Returns:
            None

        Raises:
            ProductInstallException: If an error occurred removing an image.
        """
        product = self.get_product(name, version)

        images_to_remove = product.docker_images
        other_products = [
            p for p in self.products
            if p.version != product.version or p.name != product.name
        ]

        errors = False
        # For each image to remove, check if it is shared by any other products.
        for image_name, image_version in images_to_remove:
            other_products_with_same_docker_image = [
                other_product for other_product in other_products
                if any([
                    other_image_name == image_name and other_image_version == image_version
                    for other_image_name, other_image_version in other_product.docker_images
                ])
            ]
            if other_products_with_same_docker_image:
                print(f'Not removing Docker image {image_name}:{image_version} '
                      f'used by the following other product versions: '
                      f'{", ".join(str(p) for p in other_products_with_same_docker_image)}')
            else:
                try:
                    uninstall_docker_image(
                        image_name, image_version, self.docker_api)
                except ProductInstallException as err:
                    print(
                        f'Failed to remove {image_name}:{image_version}: {err}')
                    errors = True

        if errors:
            raise ProductInstallException(f'One or more errors occurred removing '
                                          f'Docker images for {name} {version}.')

    def activate_product_hosted_repos(self, name, version):
        """Activate a product's hosted repositories.

        Args:
            name (str): The name of the product for which to activate
                repositories.
            version (str): The version of the product for which to activate
                repositories.

        Returns:
            None

        Raises:
            ProductInstallException: If an error occurred activating
                repositories.
        """
        product_to_activate = self.get_product(name, version)
        product_to_activate.activate_hosted_repos_in_group(self.nexus_api)

    def uninstall_product_hosted_repos(self, name, version):
        """Uninstall a product's hosted repositories.

        Args:
            name (str): The name of the product for which to uninstall
                repositories.
            version (str): The version of the product for which to uninstall
                repositories.

        Returns:
            None

        Raises:
            ProductInstallException: If an error occurred uninstalling
                repositories.
        """
        product_to_uninstall = self.get_product(name, version)
        product_to_uninstall.uninstall_hosted_repos(self.nexus_api)

    def activate_product_entry(self, name, version):
        """Set this product version's entry as active in the product catalog.

        This function uses the catalog_update script provided by
        cray-product-catalog.

        Args:
            name (str): The name of the product to activate.
            version (str): The version of the product to activate.

        Returns:
            None

        Raises:
            ProductInstallException: If an error occurred activating the entry.
        """
        with NamedTemporaryFile(mode='w') as temporary_file:
            # Technically the addition of {"active": True} here is redundant,
            # because running catalog_update will automatically set whatever
            # version is being updated to be "active". When running catalog_update,
            # this dictionary does not replace all the data for this product version;
            # existing keys under the product version still be there.
            temporary_file.write(safe_dump({'active': True}))
            temporary_file.flush()
            # Use os.environ so that PATH and VIRTUAL_ENV are used
            # Note: reading the file using temporary_file.name while the file
            # is already open does not work on Windows.
            # See: https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile
            os.environ.update({
                'PRODUCT': name,
                'PRODUCT_VERSION': version,
                'CONFIG_MAP': self.name,
                'CONFIG_MAP_NS': self.namespace,
                'SET_ACTIVE_VERSION': 'true',
                'VALIDATE_SCHEMA': 'true',
                'YAML_CONTENT': temporary_file.name
            })
            try:
                subprocess.check_output(['catalog_update'])
                print(f'Set {name}-{version} as active in the product catalog.')
            except subprocess.CalledProcessError as err:
                raise ProductInstallException(
                    f'Error activating {name}-{version} in product catalog: {err}'
                )

    def remove_product_entry(self, name, version):
        """Remove this product version's entry from the product catalog.

        This function uses the catalog_delete script provided by
        cray-product-catalog.

        Args:
            name (str): The name of the product to remove.
            version (str): The version of the product to remove.

        Returns:
            None

        Raises:
            ProductInstallException: If an error occurred removing the entry.
        """
        # Use os.environ so that PATH and VIRTUAL_ENV are used
        os.environ.update({
            'PRODUCT': name,
            'PRODUCT_VERSION': version,
            'CONFIG_MAP': self.name,
            'CONFIG_MAP_NS': self.namespace,
            'VALIDATE_SCHEMA': 'true'
        })
        try:
            subprocess.check_output(['catalog_delete'])
            print(f'Deleted {name}-{version} from product catalog.')
        except subprocess.CalledProcessError as err:
            raise ProductInstallException(
                f'Error removing {name}-{version} from product catalog: {err}'
            )

    def update_product_data(self, name: str, version: str, updated_product_data: dict[Any, Any]) -> None:
        """
        Function to update the cray-product-catalog ConfigMap using
        the `catalog_update.py` in cray-product-catalog.

        Args:
            name (str): The name of the product to update.
            version (str): The version of the product to update.
            updated_product_data (dict): The updated product data configmap in dict format.

        Raises:
            ProductInstallException: If an error occurred updating the ConfigMap.
        """
        with NamedTemporaryFile(mode='w') as temp_file:
            # Use os.environ so that PATH and VIRTUAL_ENV are used
            # Note: reading the file using temporary_file.name while the file
            # is already open does not work on Windows.
            # See: https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile
            temp_file.write(safe_dump(updated_product_data))
            temp_file.flush()
            os.environ.update({
                'PRODUCT': name,
                'PRODUCT_VERSION': version,
                'CONFIG_MAP': self.name,
                'CONFIG_MAP_NS': self.namespace,
                'SET_ACTIVE_VERSION': 'true',
                'VALIDATE_SCHEMA': 'true',
                'UPDATE_OVERWRITE': 'true',
                'YAML_CONTENT': temp_file.name
            })
            try:
                subprocess.check_output(['catalog_update'])
                print(f'Updated {name}-{version} in the product catalog with new product data.')
            except subprocess.CalledProcessError as err:
                raise ProductInstallException(
                    f'Error activating {name}-{version} in product catalog: {err}'
                )


class InstalledProductVersion:
    """A representation of a version of a product that is currently installed.

    Attributes:
        name: The product name.
        version: The product version.
        data: A dictionary representing the data within a given product and
              version in the product catalog, which is expected to contain a
              'component_versions' key that will point to the respective
              versions of product components, e.g. Docker images.
        nexus_charts: A model of the nexus API response of the components API.
                      See nexusctl.nexus.models.ComponentXO for more info.
    """

    def __init__(self, name, version, data, nexus_charts):
        self.name = name
        self.version = version
        self.data: dict[Any, Any] = data
        self.nexus_charts: PageComponentXO = nexus_charts

    def __str__(self):
        return f'{self.name}-{self.version}'

    @property
    def is_valid(self):
        """bool: True if this product's version data fits the schema."""
        try:
            validate(self.data)
            return True
        except ValidationError:
            return False

    @property
    def docker_images(self):
        """Get Docker images associated with this InstalledProductVersion.

        Returns:
            A list of tuples of (image_name, image_version)
        """
        component_data = self.data.get(COMPONENT_VERSIONS_PRODUCT_MAP_KEY, {})

        # If there is no 'docker' key under the component data, assume that there
        # is a single docker image named cray/cray-PRODUCT whose version is the
        # value of the PRODUCT key under component_versions.
        if COMPONENT_DOCKER_KEY not in component_data:
            return [(self._deprecated_docker_image_name, self._deprecated_docker_image_version)]

        return [(component['name'], component['version'])
                for component in component_data.get(COMPONENT_DOCKER_KEY) or []]

    @property
    def helm_charts(self) -> HelmChartTuples:
        """Get Helm charts associated with this InstalledProductVersion.
        
        Returns:
            A list of tuples of (chart_name, chart_version) `HelmChartTuples`
        """
        component_data: dict[Any, Any] = self.data.get(
            COMPONENT_VERSIONS_PRODUCT_MAP_KEY, {})

        return [(component['name'], component['version'])
                for component in component_data.get(COMPONENT_HELM_KEY) or []]

    @property
    def _deprecated_docker_image_version(self):
        """str: The Docker image version associated with this product version, or None.

        Note: this assumes that the 'component_versions' data is structured as follows:
        component_versions:
            product_name: docker_image_version

        Newer versions will structure the 'component_versions' data as follows:
        component_versions:
            product_name:
                docker:
                    docker_image_name_1: docker_image_version
                    docker_image_name_2: docker_image_version

        This method should only be used if the installed version does not have a
        component_versions->product_name->docker key.
        """
        return self.data.get(COMPONENT_VERSIONS_PRODUCT_MAP_KEY, {}).get(self.name)

    @property
    def _deprecated_docker_image_name(self):
        """str: The Docker image name associated with this product version.

        Note: this assumes that the 'component_versions' data is structured as follows:
        component_versions:
            product_name: docker_image_version

        It also assumes that the name of the singular docker image is
        'cray/cray-<product_name'.

        Newer versions will structure the 'component_versions' data as follows:
        component_versions:
            product_name:
                docker:
                    docker_image_name_1: docker_image_version
                    docker_image_name_2: docker_image_version

        This method should only be used if the installed version does not have a
        component_versions->product_name->docker key.
        """
        return f'cray/cray-{self.name}'

    @property
    def group_repositories(self):
        """[dict]: Group-type repository data dictionaries for this product version."""
        component_data = self.data.get(COMPONENT_VERSIONS_PRODUCT_MAP_KEY)
        repositories = component_data.get(COMPONENT_REPOS_KEY)
        return [repo for repo in repositories if repo.get('type') == 'group']

    @property
    def hosted_repository_names(self):
        """set(str): Hosted-type repository names for this product version."""
        component_data = self.data.get(COMPONENT_VERSIONS_PRODUCT_MAP_KEY)
        repositories = component_data.get(COMPONENT_REPOS_KEY)

        # Get all hosted repositories, plus any repos that might be under a group repo's "members" list.
        hosted_repositories = set(repo.get('name') for repo in repositories if repo.get('type') == 'hosted')
        for group_repo in self.group_repositories:
            hosted_repositories |= set(group_repo.get('members'))

        return hosted_repositories

    @property
    def clone_url(self):
        """str or None: the clone url of the configuration repo for the product, if available.
               Otherwise, None.
        """
        configuration = self.data.get('configuration')
        return configuration and configuration['clone_url']

    @staticmethod
    def _get_repo_by_name(nexus_api: NexusApi, name: str) -> Union[RepoListHostedEntry, RepoListGroupEntry]:
        """Get a repository with the specified name.

        Args:
            name (str): The name of the repository.

        Returns:
            RepoListHostedEntry: If the repository is a hosted repository
            RepoListGroupEntry: If the repository is a group repository

        Raises:
            ProductInstallException: if more than one repository with the specified name
                is found, or if none are found with the specified name.
            ProductInstallException: if an API error occurs.
        """
        try:
            repos_matching_name = nexus_api.repos.list(regex=f'^{name}$')
            if len(repos_matching_name) > 1:
                raise ProductInstallException(f'More than one repository named {name} found.')
            return repos_matching_name[0] # type: ignore
        except IndexError:
            raise ProductInstallException(f'No repository named {name} found.')
        except HTTPError as err:
            raise ProductInstallException(f'Failed to get repository {name}: {err}')

    def activate_hosted_repos_in_group(self, nexus_api):
        """Activate a version by updating its group repositories

        This uses the Nexus API to make hosted-type repos the sole entries
        in their group-type repos.

        Args:
            nexus_api (NexusApi): The nexusctl Nexus API to interface with
                Nexus.

        Returns:
            None

        Raises:
            ProductInstallException: if an error occurred activating a hosted
                repository.
        """
        errors = False
        for group_repo_data in self.group_repositories:
            members = group_repo_data['members']
            group_repo = self._get_repo_by_name(nexus_api, group_repo_data.get('name'))
            try:
                # NOTE: if one of the members does not exist, then
                # this will result in an HTTP 400 (Bad Request) error.
                nexus_api.repos.raw_group.update(
                    group_repo.name,
                    group_repo.online,
                    group_repo.storage.blobstore_name,
                    group_repo.storage.strict_content_type_validation,
                    member_names=members
                )
                print(
                    f'Updated group repository {group_repo.name} '
                    f'with member repositories: [{",".join(members)}]'
                )
            except HTTPError as err:
                errors = True
                print(f'Failed to update group repository {group_repo.name} '
                      f'with member repositories: [{",".join(members)}]. Error: {err}')
        if errors:
            raise ProductInstallException(
                f'One or more errors occurred activating repositories for {self.name} {self.version}.'
            )

    def uninstall_hosted_repos(self, nexus_api):
        """Remove a version's package repositories from Nexus.

        Args:
            nexus_api (NexusApi): The nexusctl Nexus API to interface with
                Nexus.

        Returns:
            None

        Raises:
            ProductInstallException: If an error occurred removing a repository.
        """
        errors = False
        for hosted_repo_name in self.hosted_repository_names:
            try:
                nexus_api.repos.delete(hosted_repo_name)
                print(f'Repository {hosted_repo_name} has been removed.')
            except HTTPError as err:
                if err.code == 404:
                    print(f'{hosted_repo_name} has already been removed.')
                else:
                    print(f'Failed to remove hosted repository {hosted_repo_name}: {err}')
                    errors = True
        if errors:
            raise ProductInstallException(
                f'One or more errors occurred uninstalling repositories for {self.name} {self.version}.'
            )

    def get_helm_chart_nexus_component_ids(self) -> Optional[NexusHelmChartTuples]:
        """
        Maps the names of the helm charts found in the configmap which contain (name, version).
        Nexus delete API requires that the component_id. This method searches the entire charts
        repository for the products helm charts and returns a list of Tuples that contain:
        (name, version, component_id). NexusHelmChartTuples

        Returns:
            Optional[NexusHelmChartTuples]: List of Tuples (name: str, version: str, component_id: str)
        """
        charts_to_find: HelmChartTuples = self.helm_charts
        if not charts_to_find:
            print(
                f"No helm charts found in the configmap data for {self.name}:{self.version}")
            return

        matches: NexusHelmChartTuples = list()
        for chart_tuple in charts_to_find:
            name, version = chart_tuple
            for component in self.nexus_charts.components:
                if component.name == name and component.version == version:
                    matches.append((name, version, component.id))
                    break

        return matches
