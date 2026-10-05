"""Check whether the Python 3.14 / OpenSSL 3 SSL regression is still active.

Run periodically to determine when the workaround
can be removed (verify=False in tests/aws/aws_session.py, also used by
scripts/check_deployed_pipeline.py).

Usage:
  .venv/Scripts/python.exe scripts/testing/check_ssl_regression.py  # Windows
  .venv/bin/python scripts/testing/check_ssl_regression.py           # Linux/macOS
"""

from __future__ import annotations

import socket
import ssl
import sys

HOST = "sts.us-east-1.amazonaws.com"


def main() -> int:
    print(f"Python {sys.version.split()[0]}, {ssl.OPENSSL_VERSION}")
    print(f"Checking TLS handshake (no workaround): {HOST}")

    ctx = ssl.create_default_context()  # certifi bundle, no OS store patch
    try:
        with socket.create_connection((HOST, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST):
                pass
        print()
        print("NATIVE SSL: OK")
        print("The Basic Constraints regression is no longer present.")
        print("You can remove verify=False from tests/aws/aws_session.py.")
        return 0
    except ssl.SSLCertVerificationError as e:
        print()
        print("NATIVE SSL: STILL FAILS — keep workaround active")
        print(f"  {e}")
        return 1
    except OSError as e:
        print()
        print(f"NETWORK ERROR (check connectivity): {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
