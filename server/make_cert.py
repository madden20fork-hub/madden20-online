"""Generate a self-signed cert for the EA hosts the game talks to (shadPS4 skips verification)."""
import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

out = Path(__file__).parent / "certs"
out.mkdir(exist_ok=True)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "*.ea.com")])
san = x509.SubjectAlternativeName([
    x509.DNSName("*.ea.com"), x509.DNSName("spring18.gosredirector.ea.com"),
    x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650)).add_extension(san, critical=False)
        .sign(key, hashes.SHA256()))
(out / "ea.key").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                               serialization.PrivateFormat.TraditionalOpenSSL,
                                               serialization.NoEncryption()))
(out / "ea.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
print("wrote", out)
