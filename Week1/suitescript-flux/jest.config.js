/**
 * Jest config via the SuiteCloud Unit Testing framework. It transforms SuiteScript AMD (`define`)
 * modules and stubs the N/* modules so the pure deterministic logic (flux_calc, flux_eval) can be
 * unit-tested off-platform - the same engineering hygiene as the Python build's test suites.
 */
const SuiteCloudJestConfiguration = require('@oracle/suitecloud-unit-testing/jest-configuration/SuiteCloudJestConfiguration');
const cliConfig = require('./suitecloud.config');

module.exports = SuiteCloudJestConfiguration.build({
  projectFolder: cliConfig.defaultProjectFolder,
  projectType: SuiteCloudJestConfiguration.ProjectType.ACP
});
