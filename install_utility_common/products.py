"""
Contains the ProductCatalog and InstalledProductVersion classes.

(C) Copyright 2021 Hewlett Packard Enterprise Development LP.
"""

import os
import subprocess
import warnings

from kubernetes.client import CoreV1Api
from kubernetes.client.rest import ApiException
from kubernetes.config import load_kube_config, ConfigException
from nexusctl import DockerApi, DockerClient, NexusApi, NexusClient
from nexusctl.common import DEFAULT_DOCKER_REGISTRY_API_BASE_URL, DEFAULT_NEXUS_API_BASE_URL
from urllib3.exceptions import MaxRetryError
from urllib.error import HTTPError
from yaml import safe_load, YAMLError, YAMLLoadWarning


from install_utility_common.constants import (
    COMPONENT_DOCKER_KEY,
    COMPONENT_REPOS_KEY,
    COMPONENT_VERSIONS_PRODUCT_MAP_KEY,
    PRODUCT_CATALOG_CONFIG_MAP_NAME,
    PRODUCT_CATALOG_CONFIG_MAP_NAMESPACE
)


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
                 nexus_url=DEFAULT_NEXUS_API_BASE_URL, docker_url=DEFAULT_DOCKER_REGISTRY_API_BASE_URL):
        """Create the ProductCatalog object.

        Args:
            name (str): The name of the product catalog Kubernetes config map.
            namespace (str): The namespace of the product catalog Kubernetes
                config map.

        Raises:
            ProductInstallException: if reading the config map failed.
        """
        self.name = name
        self.namespace = namespace
        self.k8s_client = self._get_k8s_api()
        self.docker_api = DockerApi(DockerClient(docker_url))
        self.nexus_api = NexusApi(NexusClient(nexus_url))
        try:
            config_map = self.k8s_client.read_namespaced_config_map(name, namespace)
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

        try:
            self.products = [
                InstalledProductVersion(product_name, product_version, product_version_data)
                for product_name, product_versions in config_map.data.items()
                for product_version, product_version_data in safe_load(product_versions).items()
            ]
        except YAMLError as err:
            raise ProductInstallException(
                f'Failed to load ConfigMap data: {err}'
            )

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
                    uninstall_docker_image(image_name, image_version, self.docker_api)
                except ProductInstallException as err:
                    print(f'Failed to remove {image_name}:{image_version}: {err}')
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


class InstalledProductVersion:
    """A representation of a version of a product that is currently installed.

    Attributes:
        name: The product name.
        version: The product version.
        data: A dictionary representing the data within a given product and
              version in the product catalog, which is expected to contain a
              'component_versions' key that will point to the respective
              versions of product components, e.g. Docker images.
    """
    def __init__(self, name, version, data):
        self.name = name
        self.version = version
        self.data = data

    def __str__(self):
        return f'{self.name}-{self.version}'

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

    @staticmethod
    def _get_repo_by_name(nexus_api, name):
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
            return repos_matching_name[0]
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
