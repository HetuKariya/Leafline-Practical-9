// Leafline Microservices CI/CD Pipeline for Windows Jenkins
//
// Pipeline:
// Checkout -> Build test images -> Unit tests + coverage
// -> Build application images -> SOAP integration tests
// -> Deploy on main branch
//
// Requirements:
// - Windows Jenkins agent
// - Docker Desktop running Linux containers
// - Docker CLI and Docker Compose v2 in PATH
// - Jenkins plugins: Pipeline, Git, JUnit
// - Optional: HTML Publisher and Coverage

def SERVICES = [
    'catalog-service',
    'auth-service',
    'order-service',
    'gateway'
]

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 45, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
        disableConcurrentBuilds()
    }

    environment {
        IMAGE_TAG = "${env.BUILD_NUMBER}"
        COMPOSE_PROJECT_NAME = "leafline-ci-${env.BUILD_NUMBER}"

        // Make Docker CLI available to Windows Jenkins build steps
        PATH = 'C:/Users/DELL/AppData/Local/Programs/DockerDesktop/resources/bin'
    }

    stages {

        stage('Checkout and Verify Tools') {
            steps {
                checkout scm

                bat '''
@echo off
setlocal

echo Checking Docker installation...
docker version --format "Docker server {{.Server.Version}}"
if errorlevel 1 exit /b 1

echo Checking Docker Compose...
docker compose version
if errorlevel 1 exit /b 1

if exist reports rmdir /s /q reports
mkdir reports

echo Environment verification complete.
exit /b 0
'''
            }
        }

        stage('Build Test Images') {
            steps {
                script {
                    def jobs = [:]

                    SERVICES.each { svc ->
                        def service = svc

                        jobs[service] = {
                            bat """
@echo off
docker build --target test -t leafline/${service}:test "${service}"
if errorlevel 1 exit /b 1
"""
                        }
                    }

                    parallel jobs
                }
            }
        }

        stage('Unit Tests and Coverage') {
            steps {
                script {
                    def jobs = [failFast: false]

                    SERVICES.each { svc ->
                        def service = svc

                        jobs[service] = {
                            bat """
@echo off

if not exist "reports\\${service}" mkdir "reports\\${service}"

docker rm -f ut-${service}-${env.BUILD_NUMBER} >NUL 2>&1

docker run --name ut-${service}-${env.BUILD_NUMBER} leafline/${service}:test sh -c "mkdir -p /app/reports && pytest -q"
set "TEST_RC=%ERRORLEVEL%"

docker cp ut-${service}-${env.BUILD_NUMBER}:/app/reports/. "reports\\${service}\\"
set "COPY_RC=%ERRORLEVEL%"

docker rm -f ut-${service}-${env.BUILD_NUMBER} >NUL 2>&1

if not "%TEST_RC%"=="0" exit /b %TEST_RC%
if not "%COPY_RC%"=="0" exit /b %COPY_RC%

exit /b 0
"""
                        }
                    }

                    parallel jobs
                }
            }
        }

        stage('Build Application and Integration Images') {
            steps {
                bat '''
@echo off

docker compose --profile test build
if errorlevel 1 exit /b 1

echo Application and integration-test images built.
'''
            }
        }

        stage('SOAP Integration Tests') {
            steps {
                script {
                    def gatewayPort =
                        20000 + (env.BUILD_NUMBER.toInteger() % 1000)

                    withEnv(["GATEWAY_PORT=${gatewayPort}"]) {
                        bat '''
@echo off

echo Starting Leafline services...

docker compose up -d --wait
if errorlevel 1 exit /b 1

if not exist "reports\\integration" mkdir "reports\\integration"

docker rm -f it-%BUILD_NUMBER% >NUL 2>&1

echo Running SOAP integration tests...

docker compose --profile test run --no-deps --name it-%BUILD_NUMBER% smoke-tests sh -c "mkdir -p /reports && pytest -v --junitxml=/reports/integration.xml -p no:cacheprovider"

set "TEST_RC=%ERRORLEVEL%"

docker cp it-%BUILD_NUMBER%:/reports/. "reports\\integration\\"
set "COPY_RC=%ERRORLEVEL%"

docker rm -f it-%BUILD_NUMBER% >NUL 2>&1

if not "%TEST_RC%"=="0" exit /b %TEST_RC%
if not "%COPY_RC%"=="0" exit /b %COPY_RC%

echo Integration tests completed.
exit /b 0
'''
                    }
                }
            }

            post {
                always {
                    bat '''
@echo off

if not exist reports mkdir reports

docker compose logs --no-color > reports\\compose.log 2>&1

docker compose --profile test down -v --remove-orphans >NUL 2>&1

exit /b 0
'''
                }
            }
        }

        stage('Deploy') {
            when {
                expression {
                    env.BRANCH_NAME == 'main' ||
                    env.GIT_LOCAL_BRANCH == 'main' ||
                    env.GIT_BRANCH in [
                        'main',
                        'origin/main',
                        'refs/remotes/origin/main'
                    ]
                }
            }

            steps {
                script {
                    withEnv([
                        'COMPOSE_PROJECT_NAME=leafline',
                        'IMAGE_TAG=latest',
                        'GATEWAY_PORT=5000'
                    ]) {
                        bat '''
@echo off

echo Deploying Leafline application...

docker compose up -d --build --wait
if errorlevel 1 exit /b 1

echo Deployment completed successfully.
'''
                    }
                }
            }
        }
    }

    post {
        always {
            echo 'Publishing JUnit test results...'

            junit(
                allowEmptyResults: true,
                testResults: 'reports/*/junit.xml,reports/integration/integration.xml'
            )

            archiveArtifacts(
                artifacts: 'reports/**',
                allowEmptyArchive: true
            )

            script {
                writeFile(
                    file: 'coverage-summary.ps1',
                    text: '''
$ErrorActionPreference = 'Continue'

$services = @(
    'catalog-service',
    'auth-service',
    'order-service',
    'gateway'
)

Write-Output '================ Coverage Summary ================'

foreach ($service in $services) {

    $path = Join-Path `
        (Join-Path 'reports' $service) `
        'coverage.xml'

    if (Test-Path -LiteralPath $path) {
        try {
            [xml]$doc = Get-Content -LiteralPath $path -Raw

            $lineRate = [double]$doc.coverage.GetAttribute('line-rate')
            $branchRate = [double]$doc.coverage.GetAttribute('branch-rate')

            $line = '{0:N1}' -f ($lineRate * 100)
            $branch = '{0:N1}' -f ($branchRate * 100)

            Write-Output (
                '{0,-16} line {1,5}%   branch {2,5}%' -f
                $service, $line, $branch
            )
        }
        catch {
            Write-Output (
                '{0}: coverage parsing failed: {1}' -f
                $service, $_.Exception.Message
            )
        }
    }
    else {
        Write-Output (
            '{0}: coverage report not found' -f $service
        )
    }
}

exit 0
'''
                )

                bat '''
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File coverage-summary.ps1
exit /b 0
'''
            }

            script {
                SERVICES.each { svc ->
                    try {
                        publishHTML(target: [
                            reportName: "Coverage - ${svc}",
                            reportDir: "reports/${svc}/htmlcov",
                            reportFiles: 'index.html',
                            keepAll: true,
                            alwaysLinkToLastBuild: true,
                            allowMissing: true
                        ])
                    } catch (Throwable err) {
                        echo "HTML Publisher unavailable for ${svc}."
                    }
                }

                try {
                    recordCoverage(
                        tools: [[
                            parser: 'COBERTURA',
                            pattern: 'reports/*/coverage.xml'
                        ]]
                    )
                } catch (Throwable err) {
                    echo 'Coverage plugin unavailable; skipping coverage trend.'
                }
            }
        }

        success {
            echo '''
            PIPELINE SUCCESSFUL!
            All services were built and tested.
            SOAP integration testing completed.
            '''
        }

        failure {
            echo '''
            PIPELINE FAILED!
            Check Console Output, Test Result,
            coverage summaries and reports/compose.log.
            '''
        }

        cleanup {
            bat """
@echo off

docker compose --profile test down -v --remove-orphans >NUL 2>&1

for %%S in (catalog-service auth-service order-service gateway) do docker image rm -f leafline/%%S:test >NUL 2>&1

docker image rm -f leafline/integration-tests:${env.BUILD_NUMBER} >NUL 2>&1

for %%S in (catalog-service auth-service order-service gateway) do docker image rm -f leafline/%%S:${env.BUILD_NUMBER} >NUL 2>&1

exit /b 0
"""
        }
    }
}