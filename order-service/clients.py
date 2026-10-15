"""SOAP clients (Zeep) that order-service uses to talk to auth-service and catalog-service.

Clients are built lazily on first use, so the service can start before its dependencies are up
(docker-compose still orders startup with health checks). Tests replace the module-level
`auth` and `catalog` objects with fakes.
"""
import os
import threading

import requests
from zeep import Client
from zeep.exceptions import Fault as ZeepFault, TransportError
from zeep.transports import Transport

AUTH_WSDL = os.environ.get("AUTH_WSDL", "http://auth-service:5002/soap/?wsdl")
CATALOG_WSDL = os.environ.get("CATALOG_WSDL", "http://catalog-service:5001/soap/?wsdl")


class UpstreamError(Exception):
    """A SOAP Fault (or network failure) coming from another microservice."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def fault_code(fault):
    code = str(getattr(fault, "code", "") or "")
    code = code.split("}")[-1].split(":")[-1]  # Zeep gives "soap11env:Client.X"; keep just "Client.X"
    return code if "." in code else f"Server.{code or 'Fault'}"


class SoapClient:
    def __init__(self, wsdl):
        self.wsdl = wsdl
        self._client = None
        self._lock = threading.Lock()

    def _service(self):
        with self._lock:
            if self._client is None:
                self._client = Client(self.wsdl, transport=Transport(timeout=5, operation_timeout=15))
        return self._client.service

    def call(self, operation, **kwargs):
        try:
            return getattr(self._service(), operation)(**kwargs)
        except ZeepFault as exc:
            raise UpstreamError(fault_code(exc), exc.message)
        except (requests.RequestException, TransportError, OSError) as exc:
            raise UpstreamError("Server.UpstreamUnavailable", f"{operation} failed: {exc}")


class AuthClient(SoapClient):
    def validate(self, token):
        return self.call("ValidateToken", token=token).user_id


class CatalogClient(SoapClient):
    def get_product(self, product_id):
        p = self.call("GetProduct", product_id=product_id)
        return {"id": p.id, "name": p.name, "price": p.price}

    def reserve(self, product_id, qty):
        self.call("ReserveStock", product_id=product_id, qty=qty)

    def release(self, product_id, qty):
        self.call("ReleaseStock", product_id=product_id, qty=qty)


auth = AuthClient(AUTH_WSDL)
catalog = CatalogClient(CATALOG_WSDL)
