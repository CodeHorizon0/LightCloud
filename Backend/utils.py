import base64

# Key encoding 
def encode_key(name: str) -> str:
    return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")

def decode_key(key: str) -> str:
    padded = key + "=" * (-len(key) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return key