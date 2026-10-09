"""Application and magnet protocol entry point."""

import argparse


def run() -> None:
    """Run the web application."""
    parser = argparse.ArgumentParser(prog="apokalypse")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--magnet", help="submit a magnet URI to the local client")
    parser.add_argument("--register-magnet", action="store_true", help="register as the Windows magnet handler")
    parser.add_argument("--unregister-magnet", action="store_true", help="restore the previous magnet handler")
    args = parser.parse_args()

    from .protocol import register_magnet_handler, submit_magnet, unregister_magnet_handler, write_handler_error

    if args.register_magnet:
        print(register_magnet_handler())
        return
    if args.unregister_magnet:
        print(unregister_magnet_handler())
        return
    if args.magnet:
        try:
            submit_magnet(args.magnet, f"http://127.0.0.1:{args.port}")
        except Exception as exc:
            write_handler_error(exc)
            raise
        return

    import uvicorn

    uvicorn.run("apokalypse.web:app", host=args.host, port=args.port)


if __name__ == "__main__":
    run()
