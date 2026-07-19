import asyncio
import gzip
import base64

# Compression/decompression
async def compress_file(src_path: str, dst_path: str, CHUNK_SIZE: int, COMPRESSION_LEVEL: int):
    def _compress():
        level = min(COMPRESSION_LEVEL, 5)
        with open(src_path, "rb") as src, gzip.open(dst_path, "wb", compresslevel=level) as dst:
            while chunk := src.read(CHUNK_SIZE):
                dst.write(chunk)

    await asyncio.to_thread(_compress)

async def decompress_file(src_path: str, dst_path: str, CHUNK_SIZE: int):
    def _decompress():
        with gzip.open(src_path, "rb") as src, open(dst_path, "wb") as dst:
            while chunk := src.read(CHUNK_SIZE):
                dst.write(chunk)
    await asyncio.to_thread(_decompress)

# Key encoding 
def encode_key(name: str) -> str:
    return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")

def decode_key(key: str) -> str:
    padded = key + "=" * (-len(key) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return key