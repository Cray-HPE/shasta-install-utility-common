// Jenkinsfile for shasta-install-utility-common Python package
// Copyright 2021 Hewlett Packard Enterprise Development LP

@Library('dst-shared@master') _

pipeline {
    agent {
        kubernetes {
            label "cray-shasta-install-utility-common-test-pod"
            containerTemplate {
                name "cray-shasta-install-utility-common-test-cont"
                image "arti.dev.cray.com/dstbuildenv-docker-master-local/cray-sle15sp3_build_environment:latest"
                ttyEnabled true
                command "cat"
            }
        }
    }

    // Configuration options applicable to the entire job
    options {
        // This build should not take long, fail the build if it appears stuck
        timeout(time: 10, unit: 'MINUTES')

        // Don't fill up the build server with unnecessary cruft
        buildDiscarder(logRotator(numToKeepStr: '5'))

        // Add timestamps and color to console output, cuz pretty
        timestamps()
    }

    stages {
        stage('Prepare') {
            steps {
                container('cray-shasta-install-utility-common-test-cont') {
                    sh "make pymod_prepare"
                }
            }
        }

        stage('Build Package') {
            steps {
                container('cray-shasta-install-utility-common-test-cont') {
                    sh "make pymod_build"
                }
            }
        }

        stage('Unit Tests') {
            steps {
                container('cray-shasta-install-utility-common-test-cont') {
                    sh "make pymod_test"
                }
            }
        }

        stage('Publish') {
            when { anyOf { branch 'release/*'; branch 'master' } }
            steps {
                container('cray-shasta-install-utility-common-test-cont') {
                    transferArti(
                        product: "internal",
                        type: "pip",
                        artifactName: "dist/*.tar.gz",
                        subdir: "shasta-install-utility-common"
                    )
                    transferArti(
                        product: "internal",
                        type: "pip",
                        artifactName: "dist/*.whl",
                        subdir: "shasta-install-utility-common"
                    )
                }
            }
        }
    }

    post('Post-build steps') {
        failure {
            emailext (
                subject: "FAILED: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]'",
                body: """<p>FAILED: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]':</p>
                <p>Check console output at &QUOT;<a href='${env.BUILD_URL}'>${env.JOB_NAME} [${env.BUILD_NUMBER}]</a>&QUOT;</p>""",
                recipientProviders: [[$class: 'CulpritsRecipientProvider'], [$class: 'RequesterRecipientProvider']]
            )
        }

        success {
            archiveArtifacts artifacts: 'dist/*', fingerprint: true
        }
    }
}
