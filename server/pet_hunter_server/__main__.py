import argparse
import ipaddress
import logging
from pathlib import Path

from werkzeug.serving import WSGIRequestHandler, run_simple

from . import create_app


class QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Private Pet Hunter G LAN protocol stub")
    parser.add_argument("--host", default="127.0.0.1", help="bind to one interface IP")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--allow-net",
        action="append",
        default=[],
        metavar="CIDR",
        help="allowed client network; required for a non-loopback bind",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "fixtures",
    )
    args = parser.parse_args()

    try:
        bind_address = ipaddress.ip_address(args.host)
        allowed_networks = [ipaddress.ip_network(value, strict=False) for value in args.allow_net]
    except ValueError as exc:
        parser.error(str(exc))

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not bind_address.is_loopback and not allowed_networks:
        parser.error("--allow-net is required when binding to a LAN interface")
    if not bind_address.is_loopback and not bind_address.is_private:
        parser.error("non-loopback bind address must be private")
    if any(not network.is_private for network in allowed_networks):
        parser.error("--allow-net accepts private networks only")

    networks = ["127.0.0.0/8", "::1/128", *(str(value) for value in allowed_networks)]
    app = create_app({"ALLOWED_NETWORKS": networks, "FIXTURE_DIR": args.fixture_dir})
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print(f"Pet Hunter G LAN prototype listening at http://{bind_address}:{args.port}")
    print("Only configured private networks and loopback clients are accepted.")
    print("Protocol responses are intentionally not implemented.")
    run_simple(
        str(bind_address),
        args.port,
        app,
        threaded=True,
        use_reloader=False,
        request_handler=QuietRequestHandler,
    )


if __name__ == "__main__":
    main()
