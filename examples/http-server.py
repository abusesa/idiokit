import idiokit
from idiokit.http.server import serve_http
from idiokit.http.handlers.router import Router
from idiokit.http.handlers.redirect import redirect
from idiokit.http.handlers.filehandler import filehandler, BakedFileSystem


@idiokit.stream
def ping(addr, request, response):
    yield response.write("PONG\n")


if __name__ == "__main__":
    router = Router({
        "ping": ping,
        "pong": redirect("/ping"),
        "/": filehandler(
            BakedFileSystem({
                "index.html": "Hello world!\n"
            }),
            index="index.html"
        )
    })

    print "Serving http://127.0.0.1:8080/"
    idiokit.main_loop(serve_http(router, "127.0.0.1", 8080))
