import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
PUBLIC = ROOT / "public"
NPM = shutil.which("npm")


def run(command):
    subprocess.run(command, cwd=FRONTEND, check=True)


def main():
    if not NPM:
        raise RuntimeError("npm was not found. Install Node.js before building the frontend.")

    install_command = [NPM, "ci"] if (FRONTEND / "package-lock.json").exists() else [NPM, "install"]
    run(install_command)
    run([NPM, "run", "build"])

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    shutil.copytree(DIST, PUBLIC)


if __name__ == "__main__":
    main()
