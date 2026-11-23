"""The https certificate for phone access (docs/08_PHONE_ACCESS_PLAN.md, step P1)."""
import ipaddress
import json
import subprocess
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import ExtendedKeyUsageOID

from core.phone_cert import VALID_DAYS, make_certificate

BACKEND = Path(__file__).resolve().parents[1]


def test_the_certificate_covers_the_laptops_addresses(tmp_path):
    meta = make_certificate(tmp_path, ["192.168.137.1", " 10.0.0.5 ", ""])
    cert = x509.load_pem_x509_certificate((tmp_path / "cert.pem").read_bytes())
    sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert sorted(str(ip) for ip in sans.get_values_for_type(x509.IPAddress)) == ["10.0.0.5", "127.0.0.1", "192.168.137.1"]
    assert sans.get_values_for_type(x509.DNSName) == ["localhost"]
    assert ExtendedKeyUsageOID.SERVER_AUTH in cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert (cert.not_valid_after_utc - cert.not_valid_before_utc).days <= VALID_DAYS
    assert meta["addresses"] == ["10.0.0.5", "127.0.0.1", "192.168.137.1"]
    assert json.loads((tmp_path / "meta.json").read_text()) == meta
    key = load_pem_private_key((tmp_path / "key.pem").read_bytes(), None)
    assert key.public_key().public_numbers() == cert.public_key().public_numbers()


def test_each_certificate_has_its_own_key(tmp_path):
    a = make_certificate(tmp_path / "a", ["192.168.1.2"])
    b = make_certificate(tmp_path / "b", ["192.168.1.2"])
    assert a["sha256"] != b["sha256"]


def test_the_desktop_entry_makes_it_from_the_command_line(tmp_path):
    out = subprocess.run([sys.executable, "desktop_entry.py", "--make-cert", str(tmp_path), "192.168.137.1"],
                         cwd=BACKEND, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1])["addresses"] == ["127.0.0.1", "192.168.137.1"]
    assert (tmp_path / "key.pem").exists() and (tmp_path / "cert.pem").exists()


def test_bad_addresses_are_refused(tmp_path):
    try:
        make_certificate(tmp_path, ["not-an-ip"])
    except ValueError:
        return
    raise AssertionError("an invalid address was accepted")


def test_ipv6_works(tmp_path):
    meta = make_certificate(tmp_path, ["fe80::1"])
    assert str(ipaddress.ip_address("fe80::1")) in meta["addresses"]
