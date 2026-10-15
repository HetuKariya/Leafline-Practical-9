# syntax=docker/dockerfile:1
FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /tests
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
ENV GATEWAY_URL=http://gateway:5000
# JUnit XML is copied out by the Jenkins pipeline.
CMD ["pytest", "-v", "--junitxml=/reports/integration.xml", "-p", "no:cacheprovider"]
