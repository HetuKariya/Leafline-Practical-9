"""order-service: Flask shell (health check) + Spyne SOAP service mounted at /soap."""
import os
import time

from flask import Flask, jsonify
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from db import init_db
from soap_service import soap_wsgi

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok", service="order-service", time=time.time())


init_db()
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/soap": soap_wsgi})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)), debug=False)
