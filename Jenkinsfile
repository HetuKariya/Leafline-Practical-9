// Leafline microservices: CI/CD pipeline (STQA Practical 9)
//
//   Checkout -> Build test images -> Unit tests + coverage -> Build images
//            -> SOAP integration tests (docker compose) -> Deploy (main only)
//
// Needs a Linux Jenkins agent with the Docker CLI + Compose v2 plugin and access to a Docker
// daemon (see jenkins/ for a ready-made Jenkins image). Plugins: Pipeline, Git, JUnit.
// Optional: HTML Publisher and Coverage (the pipeline skips them if they are not installed).

def SERVICES = ['catalog-service', 'auth-service', 'order-service', 'gateway']

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
        disableConcurrentBuilds()
    }

    environment {
        IMAGE_TAG            = "${env.BUILD_NUMBER}"
        // Every build gets its own compose project, so CI stacks never collide with each other.
        COMPOSE_PROJECT_NAME = "leafline-ci-${env.BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh '''
                    docker version --format 'Docker server {{.Server.Version}}'
                    docker compose version
                    rm -rf reports && mkdir -p reports
                '''
            }
        }

        stage('Build test images') {
            steps {
                script {
                    def jobs = [:]
                    SERVICES.each { svc ->
                        jobs[svc] = {
                            // "test" target = base image + pytest + pytest-cov + the tests/ folder
                            sh "docker build --target test -t leafline/${svc}:test ${svc}"
                        }
                    }
                    parallel jobs
                }
            }
        }

        stage('Unit tests + coverage') {
            steps {
                script {
                    def jobs = [failFast: false]       // let every service finish and report
                    SERVICES.each { svc ->
                        jobs[svc] = {
                            // pytest fails the container (exit code != 0) if a test fails OR if
                            // coverage drops under fail_under in the service's .coveragerc (80%).
                            sh """
                                mkdir -p reports/${svc}
                                docker rm -f ut-${svc}-${env.BUILD_NUMBER} >/dev/null 2>&1 || true
                                set +e
                                docker run --name ut-${svc}-${env.BUILD_NUMBER} leafline/${svc}:test
                                rc=\$?
                                docker cp ut-${svc}-${env.BUILD_NUMBER}:/app/reports/. reports/${svc}/
                                docker rm -f ut-${svc}-${env.BUILD_NUMBER} >/dev/null 2>&1
                                exit \$rc
                            """
                        }
                    }
                    parallel jobs
                }
            }
        }

        stage('Build images') {
            steps {
                sh 'docker compose build'
            }
        }

        stage('SOAP integration tests') {
            steps {
                sh '''
                    # Random-ish host port so the CI stack never clashes with a deployed one.
                    export GATEWAY_PORT=$((20000 + BUILD_NUMBER % 1000))

                    docker compose up -d --wait            # waits for every health check

                    mkdir -p reports/integration
                    docker rm -f it-$BUILD_NUMBER >/dev/null 2>&1 || true
                    set +e
                    docker compose --profile test run --name it-$BUILD_NUMBER smoke-tests
                    rc=$?
                    docker cp it-$BUILD_NUMBER:/reports/. reports/integration/
                    docker rm -f it-$BUILD_NUMBER >/dev/null 2>&1
                    exit $rc
                '''
            }
            post {
                always {
                    sh '''
                        docker compose logs --no-color > reports/compose.log 2>&1 || true
                        docker compose --profile test down -v --remove-orphans || true
                    '''
                }
            }
        }

        stage('Deploy') {
            when {
                expression { env.BRANCH_NAME == 'main' || env.GIT_BRANCH in ['main', 'origin/main'] }
            }
            steps {
                // A long-lived stack on this Docker host, separate from the throw-away CI stack.
                sh 'COMPOSE_PROJECT_NAME=leafline IMAGE_TAG=latest docker compose up -d --build --wait'
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'reports/*/junit.xml,reports/integration/integration.xml'
            archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true

            // Coverage summary straight in the console log (no plugin needed).
            sh '''
                echo "==================== Coverage summary ===================="
                for s in catalog-service auth-service order-service gateway; do
                    f=reports/$s/coverage.xml
                    if [ -f "$f" ]; then
                        line=$(grep -o 'line-rate="[0-9.]*"'   "$f" | head -1 | cut -d'"' -f2)
                        branch=$(grep -o 'branch-rate="[0-9.]*"' "$f" | head -1 | cut -d'"' -f2)
                        awk -v s="$s" -v l="$line" -v b="$branch" \
                            'BEGIN { printf "%-16s line %5.1f%%   branch %5.1f%%\\n", s, l*100, b*100 }'
                    else
                        echo "$s: no coverage report (tests did not run)"
                    fi
                done
            '''

            // Pretty reports if the optional plugins are installed.
            script {
                SERVICES.each { svc ->
                    try {
                        publishHTML(target: [
                            reportName: "Coverage - ${svc}", reportDir: "reports/${svc}/htmlcov",
                            reportFiles: 'index.html', keepAll: true,
                            alwaysLinkToLastBuild: true, allowMissing: true])
                    } catch (Throwable err) {
                        echo "HTML Publisher plugin not installed; open the archived reports/${svc}/htmlcov instead."
                    }
                }
                try {
                    recordCoverage(tools: [[parser: 'COBERTURA', pattern: 'reports/*/coverage.xml']])
                } catch (Throwable err) {
                    echo 'Coverage plugin not installed; skipping the coverage trend graph.'
                }
            }
        }
        success {
            echo 'Pipeline passed: all services tested, built and verified end to end over SOAP.'
        }
        failure {
            echo 'Pipeline failed. Check the test results tab, the coverage summary and reports/compose.log.'
        }
        cleanup {
            sh '''
                docker compose --profile test down -v --remove-orphans >/dev/null 2>&1 || true
                for s in catalog-service auth-service order-service gateway; do
                    docker image rm -f leafline/$s:test >/dev/null 2>&1 || true
                done
            '''
        }
    }
}
