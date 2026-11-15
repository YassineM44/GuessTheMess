# Third-party components

The portable package includes a Python runtime, PyInstaller bootloader, and the Python dependencies listed in `Source/tools/requirements-lock.txt` in the source archive. Runtime package metadata and available license files are included inside the executable runtime, extracted temporarily when launched.

Principal components:

- Python: Python Software Foundation license, https://docs.python.org/3/license.html
- aiohttp: Apache License 2.0, https://github.com/aio-libs/aiohttp
- aiortc / aioice: BSD license, https://github.com/aiortc
- PyAV and its wheel's FFmpeg libraries: see the bundled `av` distribution license files and https://pyav.org/docs/stable/overview/installation.html
- cryptography: Apache/BSD licensing; includes cryptographic components, https://cryptography.io/
- pyOpenSSL: Apache License 2.0, https://www.pyopenssl.org/
- PyInstaller: GPL with a bootloader exception allowing application distribution, https://pyinstaller.org/en/stable/license.html

No external fonts, image assets, CDN scripts, or paid services are used by the game. The interface illustrations are inline SVG created for this project.

This build may include a public certificate asset required by its build-time Python runtime's SSL implementation. It preserves that runtime's certificate policy and contains no game credentials.

Tailscale and browsers are separately installed third-party products, not bundled in this package. Their terms apply separately.
