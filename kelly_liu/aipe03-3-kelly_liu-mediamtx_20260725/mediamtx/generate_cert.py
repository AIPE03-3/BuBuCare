from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# MediaMTX 主機 IP 屬於機敏部署資訊，必須由未提交 Git 的環境變數提供。
SERVER_IP = os.environ.get("MEDIAMTX_SERVER_IP")
if not SERVER_IP:
    raise RuntimeError("請先設定 MEDIAMTX_SERVER_IP 環境變數")

private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, SERVER_IP),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local MediaMTX"),
])

now = datetime.now(timezone.utc)

certificate = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(private_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - timedelta(minutes=5))
    .not_valid_after(now + timedelta(days=3650))
    .add_extension(
        x509.SubjectAlternativeName([
            x509.IPAddress(ip_address(SERVER_IP)),
            x509.DNSName("localhost"),
        ]),
        critical=False,
    )
    .add_extension(
        x509.BasicConstraints(ca=True, path_length=None),
        critical=True,
    )
    .add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=True,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    .add_extension(
        x509.ExtendedKeyUsage([
            ExtendedKeyUsageOID.SERVER_AUTH,
        ]),
        critical=False,
    )
    .sign(private_key, hashes.SHA256())
)

Path("server.key").write_bytes(
    private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
)

Path("server.crt").write_bytes(
    certificate.public_bytes(serialization.Encoding.PEM)
)

print("已建立 server.key")
print("已建立 server.crt")
print(f"憑證 IP：{SERVER_IP}")
