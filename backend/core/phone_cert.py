"""
The https certificate for phone access (docs/08_PHONE_ACCESS_PLAN.md, step P1).

The desktop app's phone server needs a certificate for the laptop's addresses on the local network. PKOS makes its own
(self-signed, so the phone shows a one-time "not trusted" warning) with the `cryptography` package it already ships:
`pkos-api.exe --make-cert <dir> <ip,ip,...>`. The private key never leaves the data folder.
"""
import datetime
import ipaddress
import json
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

VALID_DAYS = 397  # phones refuse server certificates valid for much longer


def make_certificate(directory: str | os.PathLike, addresses: list[str]) -> dict:
    """Writes key.pem, cert.pem and meta.json for the given IPv4/IPv6 addresses (plus localhost). Returns the meta."""
    ips = sorted({str(ipaddress.ip_address(a.strip())) for a in addresses if a.strip()} | {"127.0.0.1"})
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PKOS on this laptop"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PKOS")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                     data_encipherment=False, key_agreement=True, key_cert_sign=False, crl_sign=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    key_file = folder / "key.pem"
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    (folder / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    meta = {
        "addresses": ips,
        "not_after": cert.not_valid_after_utc.isoformat(),
        "sha256": cert.fingerprint(hashes.SHA256()).hex(":").upper(),
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
