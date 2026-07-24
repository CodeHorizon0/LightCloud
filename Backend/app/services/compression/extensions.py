TEXT_EXTENSIONS = {
    # Text
    ".txt", ".md", ".markdown", ".rst", ".rtf", ".tex", ".csv", ".tsv",
    ".log", ".ndjson", ".jsonl",

    # Data/config
    ".json", ".json5", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg",
    ".conf", ".config", ".env", ".properties", ".plist",

    # Web
    ".html", ".htm", ".xhtml", ".css", ".scss", ".sass", ".less",
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",

    # Python
    ".py", ".pyw", ".pyi", "pyc"

    # C/C++
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp",

    # JVM
    ".java", ".kt", ".kts", ".scala", ".groovy",

    # Rust/Go
    ".rs", ".go",

    # Other languages
    ".rb", ".php", ".swift", ".m", ".mm", ".dart",
    ".lua", ".r", ".pl", ".pm", ".ex", ".exs",
    ".erl", ".hrl", ".fs", ".fsx", ".vb",

    # Shell/scripts
    ".sh", ".bash", ".zsh", ".fish", ".bat", ".cmd", ".ps1",

    # SQL/query
    ".sql", ".graphql", ".gql",

    # DevOps
    ".dockerfile", ".makefile", ".mk",
    ".tf", ".hcl",

    # Config/package
    ".lock", ".npmrc", ".editorconfig",

    # Assembly
    ".asm", ".s",
}


LOSSLESS_IMAGE_EXTENSIONS = {
    ".png", ".bmp", ".dib",
    ".tif", ".tiff",
    ".gif",
    ".ico",
    ".webp",
    ".avif",
    ".jxl",
    ".qoi",
    ".dds",
    ".exr",
    ".hdr",
    ".pcx",
    ".ppm",
    ".pgm",
    ".pbm",
}


LOSSY_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".jpe", ".jfif",
    ".heic", ".heif",
    ".jp2", ".j2k", ".jpf",
    ".webp",
}


VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mov", ".qt",
    ".mkv", ".webm",
    ".avi", ".divx", ".xvid",
    ".wmv",
    ".mpg", ".mpeg", ".mpe",
    ".flv", ".f4v",
    ".3gp", ".3g2",
    ".ts", ".m2ts", ".mts",
    ".vob",
    ".ogv",
}


AUDIO_EXTENSIONS = {
    ".wav",
    ".flac",
    ".mp3",
    ".aac",
    ".m4a",
    ".ogg",
    ".oga",
    ".opus",
    ".wma",
    ".aiff",
    ".aif",
    ".alac",
    ".ape",
    ".mid",
    ".midi",
}


ARCHIVE_EXTENSIONS = {
    ".zip",
    ".gz",
    ".gzip",
    ".bz2",
    ".bzip2",
    ".xz",
    ".lz",
    ".lz4",
    ".zst",
    ".zstd",
    ".7z",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz",
    ".tbz2",
    ".txz",
    ".cab",
    ".arj",
    ".lzh",
    ".lha",
    ".iso",
    ".img",
}


EXECUTABLE_EXTENSIONS = {
    ".exe",
    ".dll",
    ".sys",
    ".com",
    ".scr",
    ".msi",
    ".bin",
    ".run",
    ".app",
    ".elf",
    ".so",
    ".dylib",
    ".o",
    ".obj",
    ".a",
    ".lib",
    ".class",
    ".jar",
    ".war",
    ".apk",
    ".ipa",
}


DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".epub",
}


FONT_EXTENSIONS = {
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
}


DATABASE_EXTENSIONS = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".mdb",
    ".accdb",
    ".bak",
    ".dump",
}


MODEL_3D_EXTENSIONS = {
    ".obj",
    ".fbx",
    ".dae",
    ".blend",
    ".gltf",
    ".glb",
    ".3ds",
    ".stl",
    ".ply",
}


DISK_IMAGE_EXTENSIONS = {
    ".iso",
    ".img",
    ".dmg",
    ".vhd",
    ".vhdx",
    ".vmdk",
    ".qcow",
    ".qcow2",
}


MIME_BY_EXTENSION = {
    # Text
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".rst": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".xml": "application/xml",
    ".toml": "application/toml",

    # Web
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".jsx": "application/javascript",
    ".ts": "application/typescript",
    ".tsx": "application/typescript",

    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".jxl": "image/jxl",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".ico": "image/x-icon",

    # Video
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",

    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".aac": "audio/aac",

    # Archives
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".bz2": "application/x-bzip2",
    ".xz": "application/x-xz",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
    ".tar": "application/x-tar",

    # Executables
    ".exe": "application/vnd.microsoft.portable-executable",
    ".dll": "application/vnd.microsoft.portable-executable",
    ".elf": "application/x-elf",
    ".so": "application/x-sharedlib",

    # Documents
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",

    # Fonts
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

MAGIC_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"BM": "image/bmp",
    b"II*\x00": "image/tiff",
    b"MM\x00*": "image/tiff",
    b"\x00\x00\x01\x00": "image/x-icon",
    b"RIFF": "application/riff",
    b"MZ": "application/x-dosexec",
    b"\x7fELF": "application/x-elf",
    b"\xfe\xed\xfa\xce": "application/x-mach-binary",
    b"\xfe\xed\xfa\xcf": "application/x-mach-binary",
    b"\xcf\xfa\xed\xfe": "application/x-mach-binary",
    b"\xca\xfe\xba\xbe": "application/x-mach-binary",
    b"PK\x03\x04": "application/zip",
    b"PK\x05\x06": "application/zip",
    b"PK\x07\x08": "application/zip",
    b"BZh": "application/bzip2",
    b"\xfd7zXZ\x00": "application/xz",
    b"\x1f\x8b": "application/gzip",
    b"7z\xbc\xaf'\x1c": "application/x-7z-compressed",
}