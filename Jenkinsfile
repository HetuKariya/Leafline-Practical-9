// Leafline Microservices CI/CD Pipeline
// Windows Jenkins + Docker Desktop
//
// Checkout -> Build test images -> Unit tests + coverage
// -> Build application images -> SOAP integration tests
// -> Deploy on main branch

def SERVICES = [
    'catalog-service',
    'auth-service',
    'order-service',
    'gateway'
]

def DOCKER_BIN =
    'C:/Users/DELL/AppData/Local/Programs/DockerDesktop/resources/bin'

pipeline {

    // IMPORTANT: Use the same Jenkins node as the working project.
    agent {
        node {
            label 'local'
        }
    }

    options {
        timestamps()
        timeout(time: 45, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
        disableConcurrentBuilds()
    }

    environment {
        IMAGE_TAG = "${env.BUILD_NUMBER}"
        COMPOSE_PROJECT_NAME = "leafline-ci-${env.BUILD_NUMBER}"
    }

    stages {

        stage('Checkout and Verify Docker') {
            steps {
                checkout scm

                withEnv(["PATH+DOCKER=${DOCKER_BIN}"]) {
                    bat '''
@echo off
echo ===== Docker installation =====

where docker
if errorlevel 1 exit /b 1

docker --version
if errorlevel 1 exit /b 1

echo ===== Docker Compose =====

docker compose version
if errorlevel 1 exit /b 1

echo ===== Docker Engine =====

docker version
if errorlevel 1 exit /b 1

if exist reports rmdir /s /q reports
mkdir reports

echo Docker verification successful.
'''
                }
            }
        }

        stage('Build Test Images') {
            steps {
                script {
                    def jobs = [:]

                    SERVICES.each { svc ->
                        def service = svc

                        jobs[service] = {
                            withEnv(["PATH+DOCKER=${DOCKER_BIN}"]) {
                                bat """
@echo off
docker build --target test -t leafline/${service}:test "${service}"
if errorlevel 1 exit /b 1
"""
                            }
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
                            withEnv(["PATH+DOCKER=${DOCKER_BIN}"]) {
                                bat """
@echo off

if not exist "reports\\\\${service}" mkdir "reports\\\\${service}"

docker rm -f ut-${service}-${env.BUILD_NUMBER} >NUL 2>&1

docker run --name ut-${service}-${env.BUILD_NUMBER} leafline/${service}:test sh -c "mkdir -p /app/reports && pytest -q"

set "TEST_RC=%ERRORLEVEL%"

docker cp ut-${service}-${env.BUILD_NUMBER}:/app/reports/. "reports\\\\${service}\\\\"

set "COPY_RC=%ERRORLEVEL%"

docker rm -f ut-${service}-${env.BUILD_NUMBER} >NUL 2>&1

if not "%TEST_RC%"=="0" exit /b %TEST_RC%
if not "%COPY_RC%"=="0" exit /b %COPY_RC%

exit /b 0
"""
                            }
                        }
                    }

                    parallel jobs
                }
            }
        }

        stage('Build Application and Integration Images') {
            steps {
                withEnv(["PATH+DOCKER=${DOCKER_BIN}"]) {
                    bat '''
@echo off

docker compose --profile test build
if errorlevel 1 exit /b 1

echo All application and integration images built.
'''
                }
            }
        }

        stage('SOAP Integration Tests') {
            steps {
                script {
                    def gatewayPort =
                        20000 + (env.BUILD_NUMBER.toInteger() % 1000)

                    withEnv([
                        "PATH+DOCKER=${DOCKER_BIN}",
                        "GATEWAY_PORT=${gatewayPort}"
                    ]) {
                        bat '''
@echo off

echo Starting Leafline services...

docker compose up -d --wait
if errorlevel 1 exit /b 1

if not exist "reports\\\\integration" mkdir "reports\\\\integration"

docker rm -f it-%BUILD_NUMBER% >NUL 2>&1

echo Running SOAP integration tests...

docker compose --profile test run --no-deps --name it-%BUILD_NUMBER% smoke-tests sh -c "mkdir -p /reports && pytest -v --junitxml=/reports/integration.xml -p no:cacheprovider"

set "TEST_RC=%ERRORLEVEL%"

docker cp it-%BUILD_NUMBER%:/reports/. "reports\\\\integration\\\\"

set "COPY_RC=%ERRORLEVEL%"

docker rm -f it-%BUILD_NUMBER% >NUL 2>&1

if not "%TEST_RC%"=="0" exit /b %TEST_RC%
if not "%COPY_RC%"=="0" exit /b %COPY_RC%

echo SOAP integration tests completed.
exit /b 0
'''
                    }
                }
            }

            post {
                always {
                    withEnv(["PATH+DOCKER=${DOCKER_BIN}"]) {
                        bat '''
@echo off

docker compose logs --no-color > reports\\\\compose.log 2>&1

docker compose --profile test down -v --remove-orphans >NUL 2>&1

exit /b 0
'''
                    }
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
                withEnv([
                    "PATH+DOCKER=${DOCKER_BIN}",
                    'COMPOSE_PROJECT_NAME=leafline',
                    'IMAGE_TAG=latest',
                    'GATEWAY_PORT=5000'
                ]) {
                    bat '''
@echo off

echo Deploying Leafline...

docker compose up -d --build --wait
if errorlevel 1 exit /b 1

echo Deployment successful.
'''
                }
            }
        }
    }

    post {

        always {
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
$services = @(
    'catalog-service',
    'auth-service',
    'order-service',
    'gateway'
)

Write-Output '============= Coverage Summary ============='

foreach ($service in $services) {

    $path = "reports/$service/coverage.xml"

    if (Test-Path $path) {
        try {
            [xml]$doc = Get-Content $path -Raw

            $line = [double]$doc.coverage.GetAttribute('line-rate') * 100
            $branch = [double]$doc.coverage.GetAttribute('branch-rate') * 100

            Write-Output (
                '{0,-16} Line {1:N1}%  Branch {2:N1}%' -f
                $service, $line, $branch
            )
        }
        catch {
            Write-Output "$service : Unable to parse coverage report"
        }
    }
    else {
        Write-Output "$service : Coverage report unavailable"
    }
}
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
                        echo "HTML coverage publication skipped for ${svc}."
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
                    echo 'Coverage plugin unavailable; skipping coverage trends.'
                }
            }
        }

        success {
            echo 'SUCCESS: Leafline build, unit tests and SOAP integration tests passed.'
        }

        failure {
            echo 'FAILED: Check Console Output, Test Result and reports/compose.log.'
        }

        cleanup {
            withEnv(["PATH+DOCKER=${DOCKER_BIN}"]) {
                bat """
@echo off

docker compose --profile test down -v --remove-orphans >NUL 2>&1

for %%S in (catalog-service auth-service order-service gateway) do docker image rm -f leafline/%%S:test >NUL 2>&1

docker image rm -f leafline/integration-tests:latest >NUL 2>&1

exit /b 0
"""
            }
        }
    }
}