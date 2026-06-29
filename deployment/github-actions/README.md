GitHub only triggers workflows from `.github/workflows/`, so the actual
CI/CD pipeline lives at `../../.github/workflows/ci.yml`. This folder exists
to satisfy the deployment/ directory layout and to hold any deploy-only
scripts referenced by that workflow.
