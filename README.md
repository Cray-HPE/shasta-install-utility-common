# install-utility-common

## Using install-utility-common

### Add a dependency on install-utility-common

```commandline
$ cat requirements.txt
install-utility-common
```

### Using the library

The main class to interact with is the ProductCatalog class, which provides
several functions for activation and removal of products. This uses the product
catalog data discussed above to determine the component versions to activate/uninstall.

```python
from install_utility_common import ProductCatalog

product_catalog = ProductCatalog()
# Activate a version
product_catalog.activate_product_hosted_repos('sat', '2.1.0') # Make all of SAT 2.1.0's hosted repos active in group
# Uninstall a version
product_catalog.remove_product_docker_images('sat', '2.0.0') # Remove Docker images for SAT 2.0.0
product_catalog.uninstall_product_hosted_repos('sat', '2.0.0') # Remove hosted repos for SAT 2.0.0
product_catalog.remove_product_entry('sat', '2.0.0') # Remove SAT 2.0.0 from the catalog
```


## How install-utility-common works with the Product Catalog

For a product to use ``install-utility-common`` to support uninstall and downgrade,
it must register component version data in the ``cray-product-catalog`` Kubernetes
ConfigMap at install time, in order to specify the various types and versions of
components that make up the product version. This is expected to be done within
``install.sh`` by running the ``cray-product-catalog-update`` image using ``podman``.
For example, the SAT 2.3 release would insert something like this, to specify the two
Docker images, one group repository and one hosted repository that go with SAT
version ``2.3.1``.

```
component_versions:
  docker:
  - name: cray/cray-sat
    version: 3.9.9
  - name: cray/sat-cfs-install
    version: 1.8.0
  repositories:
  - members:
    - sat-2.3.1-sle-15sp2
    name: sat-sle-15sp2
    type: group
  - name: sat-2.3.1-sle-15sp2
    type: hosted
```

## Module documentation

### Requirements

At a minimum, this requires Sphinx to be installed. Install the ``requirements-dev.txt`` file.

```commandline
$ pip install -r requirements-dev.txt
```

### Build and view documentation

```commandline
$ cd docs/
$ make html
$ open _build/html/index.html
```

## See also

For a more detailed overview of the uninstall/downgrade support design, see:
https://connect.us.cray.com/confluence/display/XCCS/Uninstall+and+Downgrade+Support+Across+Products

For more on the ``cray-product-catalog-update`` image, see:
https://github.com/Cray-HPE/cray-product-catalog

For the exact schema for product catalog data, see:
https://github.com/Cray-HPE/cray-product-catalog/blob/master/cray_product_catalog/schema/schema.yaml