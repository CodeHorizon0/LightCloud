# LightCloud
LightCloud - open source cloud storage writen on **fastapi** &amp; **react**. 

> [!WARNING]
> This project was completed as part of a course project and is not recommended for use in a production environment until it has been significantly improved.

## Web app Architecture
The application uses a headless architecture because the backend and frontend are separated. However, you can always build the frontend using Vite and add it as an HTMLResponse to the server code.

## Current Features
JWT Account authorization

Real time capabilities - synchronization of file metadata with the client via SSE

Multipart file upload to the server

Selective compression based on file type analysis

Selective preview of files when possible

Downloading and deleting files

Adaptive UI design for PCs and phones

## Planned Features

1.Advanced Preview (Markdown formatting, code highlighting)

2.Expanding the list of supported files for compression and preview

3.Offline Cache Viewing in PWA Mode

4.Some frontend changes for improved responsiveness

5.Backend optimizations, especially RAM consumption when uploading files

6.Files for deployment via Docker

7.Vulnerability fixes and code refactoring
