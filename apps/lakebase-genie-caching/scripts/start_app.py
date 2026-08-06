"""Start the agent app locally for development."""

import subprocess
import sys


def main():
    subprocess.run(
        [
            sys.executable, "-m", "uvicorn",
            "agent_server.start_server:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
