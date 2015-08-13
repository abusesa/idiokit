import idiokit
from idiokit.http.server import serve_http
from idiokit.http.handlers.router import Router


@idiokit.stream
def hello(addr, request, response):
    yield response.write("HELLO\n")


@idiokit.stream
def ping(addr, request, response):
    yield response.write("PONG\n")


if __name__ == "__main__":
    router = Router({
        "hello": hello,
        "ping": ping
    })
    idiokit.main_loop(serve_http(router, "127.0.0.1", 8080))
