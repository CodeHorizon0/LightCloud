import base64
import binascii


def encode_key(name: str) -> str:
    return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")


def decode_key(key: str) -> str:
    padded = key + "=" * (-len(key) % 4)
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
    except (UnicodeError, binascii.Error):
        return key
    return decoded if encode_key(decoded) == key else key
