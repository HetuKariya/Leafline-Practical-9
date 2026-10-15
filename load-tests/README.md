Optional, carried over from the original project. The REST API is unchanged (the gateway still
serves `/api/*`), so Locust works as before:

    pip install -r requirements-loadtest.txt
    locust -f locustfile.py --host http://localhost:5000
