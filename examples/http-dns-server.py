import idiokit
from idiokit.http.server import serve_http
from idiokit.http.handlers.router import Router
from idiokit.http.handlers.redirect import redirect


@idiokit.stream
def ping(addr, request, response):
    yield response.write("PONG\n")


if __name__ == "__main__":
    router = Router({
        "ping": ping,
        "pong": redirect("/ping")
    })
    idiokit.main_loop(serve_http(router, "127.0.0.1", 8080))
