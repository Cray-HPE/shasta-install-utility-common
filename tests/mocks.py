"""
Mock data for shasta_install_utility_common unit tests.

(C) Copyright 2021-2022 Hewlett Packard Enterprise Development LP.
"""

from base64 import b64encode

from yaml import safe_dump


# Two versions of SAT that have no images in common with one another.
SAT_VERSIONS = {
    '2.0.0': {
        'component_versions': {
            'docker': [
                {'name': 'cray/cray-sat', 'version': '1.0.0'},
                {'name': 'cray/sat-cfs-install', 'version': '1.4.0'}
            ],
            'repositories': [
                {'name': 'sat-sle-15sp2', 'type': 'group', 'members': ['sat-2.0.0-sle-15sp2']},
                {'name': 'sat-2.0.0-sle-15sp2', 'type': 'hosted'}
            ]
        }
    },
    '2.0.1': {
        'component_versions': {
            'docker': [
                {'name': 'cray/cray-sat', 'version': '1.0.1'},
                {'name': 'cray/sat-other-image', 'version': '1.4.0'}
            ],
            'repositories': [
                {'name': 'sat-sle-15sp2', 'type': 'group', 'members': ['sat-2.0.1-sle-15sp2']},
                {'name': 'sat-2.0.1-sle-15sp2', 'type': 'hosted'}
            ]
        }
    },
}

# Two versions of COS, where one of the images is the same between them.
COS_VERSIONS = {
    '2.0.0': {
        'component_versions': {
            'docker': [
                {'name': 'cray/cray-cos', 'version': '1.0.0'},
                {'name': 'cray/cos-cfs-install', 'version': '1.4.0'}
            ]
        }
    },
    '2.0.1': {
        'component_versions': {
            'docker': [
                {'name': 'cray/cray-cos', 'version': '1.0.1'},
                {'name': 'cray/cos-cfs-install', 'version': '1.4.0'}
            ],
            'repositories': [
                {'name': 'cos-sle-15sp2', 'type': 'group', 'members': ['cos-2.0.1-sle-15sp2']},
                {'name': 'cos-2.0.1-sle-15sp2', 'type': 'hosted'}
            ]
        }
    },
}

# One version of "Other Product" that also uses cray/cray-sat:1.0.1
OTHER_PRODUCT_VERSION = {
    '2.0.0': {
        'component_versions': {
            'docker': [
                {'name': 'cray/cray-sat', 'version': '1.0.1'},
            ],
            'repositories': [
                {'name': 'sat-sle-15sp2', 'type': 'group', 'members': ['sat-2.0.0-sle-15sp2']},
                {'name': 'sat-2.0.0-sle-15sp2', 'type': 'hosted'}
            ]
        }
    }
}


# A mock version of the data returned when querying the Product Catalog ConfigMap
MOCK_PRODUCT_CATALOG_DATA = {
    'sat': safe_dump(SAT_VERSIONS),
    'cos': safe_dump(COS_VERSIONS),
    'other_product': safe_dump(OTHER_PRODUCT_VERSION)
}


# Some of the data returned by:
# CoreV1Api().read_namespaced_secret(name='nexus-admin-credential', namespace='nexus')
MOCK_K8S_CRED_SECRET_DATA = {
    'password': b64encode('mock_password'.encode()),
    'username': b64encode('mock_username'.encode())
}
