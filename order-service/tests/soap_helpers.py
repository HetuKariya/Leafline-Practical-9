"""Helpers to call a Spyne SOAP service through Flask's test client and read the XML reply."""
from lxml import etree

NS = "http://leafline.example.com/soap"
ENV = "http://schemas.xmlsoap.org/soap/envelope/"


def envelope(op, params=None, token=None):
    header = (f"<soapenv:Header><ns:AuthHeader><ns:token>{token}</ns:token></ns:AuthHeader></soapenv:Header>"
              if token is not None else "")
    args = "".join(f"<ns:{k}>{v}</ns:{k}>" for k, v in (params or {}).items())
    return (f'<soapenv:Envelope xmlns:soapenv="{ENV}" xmlns:ns="{NS}">{header}'
            f"<soapenv:Body><ns:{op}>{args}</ns:{op}></soapenv:Body></soapenv:Envelope>")


class Reply:
    def __init__(self, response):
        self.status = response.status_code
        self.root = etree.fromstring(response.data)
        self.body = self.root.find(f"{{{ENV}}}Body")[0]

    @property
    def is_fault(self):
        return etree.QName(self.body).localname == "Fault"

    @property
    def fault_code(self):
        return (self.body.findtext("faultcode") or "").split(":")[-1]   # Spyne sends "soap11env:Client.X"

    @property
    def fault_text(self):
        return self.body.findtext("faultstring")

    def all(self, name):
        return [e for e in self.body.iter() if etree.QName(e).localname == name]

    def text(self, name):
        found = self.all(name)
        return found[0].text if found else None

    def number(self, name):
        return float(self.text(name))


def soap_call(client, op, params=None, token=None):
    resp = client.post("/soap/", data=envelope(op, params, token),
                       headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": op})
    return Reply(resp)
