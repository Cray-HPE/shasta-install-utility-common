// Jenkinsfile for shasta-install-utility-common Python package
// Copyright 2021 Hewlett Packard Enterprise Development LP

@Library('dst-shared@master') _

pythonPackageBuildPipeline {
    packageName = "shasta-install-utility-common"
    buildPrepScript = "build_scripts/runBuildPrep.sh"
    unitTestScript = "build_scripts/runUnitTest.sh"
    buildScript = "build_scripts/buildPackages.sh"
}
