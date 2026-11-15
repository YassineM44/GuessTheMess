"""Package the game as one Windows EXE. Run from a prepared Python environment.

From Source: python -m pip install -r requirements.txt pyinstaller
             python tools/build_portable.py
Build files live in a temporary directory and are removed automatically.
"""
import importlib.metadata as metadata
import shutil
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
RUNTIME_PACKAGES = ["aiohttp", "aiortc", "aioice", "aiohappyeyeballs", "aiosignal", "attrs",
                    "av", "cryptography", "google-crc32c", "pyee", "pylibsrtp", "pyopenssl",
                    "dnspython", "ifaddr", "typing-extensions", "cffi", "idna", "pycparser",
                    "yarl", "multidict", "frozenlist", "propcache"]


def main():
    with tempfile.TemporaryDirectory(prefix=".build-", dir=PROJECT) as directory:
        work = Path(directory).resolve()
        if work.parent != PROJECT.resolve():
            raise RuntimeError("Build directory is outside the project.")
        command = [sys.executable, "-B", "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
                   "--distpath", str(work / "bin"), "--workpath", str(work / "build"),
                   "--specpath", str(work), "--name", "GuessTheMess",
                   "--add-data", f"{ROOT / 'web'};web", "--add-data", f"{ROOT / 'words.json'};.",
                   "--collect-all", "aiortc", "--collect-all", "aioice", "--exclude-module", "playwright"]
        # Preserve the build interpreter's certificate policy when it supplies this public asset.
        cert = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
        if cert.exists():
            command += ["--add-data", f"{cert};."]
        python_license = Path(sys.base_prefix) / "LICENSE.txt"
        if python_license.exists():
            command += ["--add-data", f"{python_license};python-license"]
        for name in RUNTIME_PACKAGES:
            command += ["--copy-metadata", name]
        command += [str(ROOT / "server.py")]
        subprocess.run(command, cwd=ROOT, check=True)
        shutil.copy2(work / "bin" / "GuessTheMess.exe", PROJECT / "GuessTheMess.exe")
        (ROOT / "tools" / "requirements-lock.txt").write_text(
            "# Exact runtime dependency versions used for this build.\n" +
            "\n".join(f"{name}=={metadata.version(name)}" for name in RUNTIME_PACKAGES) + "\n",
            encoding="utf-8")
    print("Ready: GuessTheMess.exe. Temporary build files removed.")


if __name__ == "__main__":
    main()
