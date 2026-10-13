"""Start the local Neon Chess server."""

from http.server import ThreadingHTTPServer

from server import ChessHandler


def main() -> None:
    address = ("127.0.0.1", 8765)
    server = ThreadingHTTPServer(address, ChessHandler)
    print(f"Neon Chess running at http://{address[0]}:{address[1]}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
