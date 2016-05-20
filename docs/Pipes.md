# Pipes

## Sending Output, Receiving Input

```python
import idiokit


@idiokit.stream
def produce_numbers(count):
    for number in range(1, count + 1):
        print "Sending number", number
        yield idiokit.send(number)


idiokit.main_loop(produce_numbers(5))
```

```console
$ python example.py
```

Why does this stall? Laziness. Use `idiokit.consume`, the `/dev/null` of streams.

```python
idiokit.main_loop(produce_numbers(5) | idiokit.consume())
```

```
$ python example.py
Sending number 1
Sending number 2
Sending number 3
Sending number 4
Sending number 5
```

Creating our own consumer:

```python
import idiokit


...


@idiokit.stream
def print_numbers():
    while True:
        number = yield idiokit.next()
        print "Received number", number


idiokit.main_loop(produce_numbers(10) | print_numbers())
```

```console
$ python example.py
Sending number 1
Sending number 2
Received number 1
Sending number 3
Received number 2
Sending number 4
Received number 3
Sending number 5
Received number 4
Received number 5
```


## Output + Input Redirection

```python
import idiokit


...


@idiokit.stream
def filter_even():
    while True:
        number = yield idiokit.next()

        if number % 2 == 0:
            yield idiokit.send(number)


@idiokit.stream
def filter_squares():
    while True:
        number = yield idiokit.next()

        if int(number ** 0.5) ** 2 == number:
            yield idiokit.send(number)


@idiokit.stream
def produce_even_numbers(count):
    yield produce_numbers(count) | filter_even()


@idiokit.stream
def print_squares():
    yield filter_squares() | print_numbers()


idiokit.main_loop(produce_even_numbers(20) | print_squares())
```

```console
$ python example.py
Sending number 1
Sending number 2
Sending number 3
Sending number 4
Sending number 5
Sending number 6
Received number 4
Sending number 7
Sending number 8
Sending number 9
Sending number 10
Sending number 11
Sending number 12
Sending number 13
Sending number 14
Sending number 15
Sending number 16
Sending number 17
Sending number 18
Received number 16
Sending number 19
Sending number 20
```


## Stopping & Return Values

```python
import idiokit


...


@idiokit.stream
def sum_numbers():
    result = 0

    while True:
        try:
            number = yield idiokit.next()
        except StopIteration:
            idiokit.stop(result)

        yield idiokit.send(number)
        result += number


@idiokit.stream
def main(count):
    total_sum = yield produce_numbers(count) | sum_numbers() | print_numbers()
    print "The sum of integers until", count, "is", total_sum


idiokit.main_loop(main(6))
```

```console
$ python example.py
Sending number 1
Sending number 2
Received number 1
Sending number 3
Received number 2
Sending number 4
Received number 3
Sending number 5
Received number 4
Sending number 6
Received number 5
Received number 6
The sum of integers until 6 is 21
```


# Exception Propagation, Broken Pipes

```python
import idiokit


@idiokit.stream
def produce_numbers(count):
    for number in range(1, count + 1):
        print "Sending number", number
        yield idiokit.send(number)


@idiokit.stream
def print_numbers():
    while True:
        number = yield idiokit.next()
        if number > 5:
            raise ValueError("can't handle numbers larger than 5")
        print "Received number", number


idiokit.main_loop(produce_numbers(100) | print_numbers())
```

```console
$ python example.py
Sending number 1
Sending number 2
Received number 1
Sending number 3
Received number 2
Sending number 4
Received number 3
Sending number 5
Received number 4
Sending number 6
Received number 5
Sending number 7
Traceback (most recent call last):
  File "example.py", line 20, in <module>
    idiokit.main_loop(produce_numbers(1000) | print_numbers())
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 354, in _next
    next = require_stream(self._gen.send(peel_args(args)))
  File "example.py", line 16, in print_numbers
    raise ValueError("can't handle numbers larger than 5")
ValueError: can't handle numbers larger than 5
```


## Multiple Inputs & Outputs

```python
import idiokit


@idiokit.stream
def produce_numbers(name, count):
    for number in range(1, count + 1):
        print name, "sending number", number
        yield idiokit.send(name, number)


@idiokit.stream
def print_numbers(name):
    while True:
        sender, number = yield idiokit.next()
        print name, "got number", number, "from", sender


@idiokit.stream
def main():
    producer_a = produce_numbers("Producer A", 3)
    producer_b = produce_numbers("Producer B", 3)
    printer_x = print_numbers("Printer X")
    printer_y = print_numbers("Printer Y")

    # Using idiokit.pipe here just to allow nicer formatting.
    yield idiokit.pipe(
        producer_a | printer_x,
        producer_b | printer_x,
        producer_a | printer_y,
        producer_b | printer_y
    )


idiokit.main_loop(main())
```

```console
$ python example.py
Producer A sending number 1
Producer B sending number 1
Producer A sending number 2
Printer X got number 1 from Producer A
Printer Y got number 1 from Producer A
Producer B sending number 2
Printer X got number 1 from Producer B
Printer Y got number 1 from Producer B
Producer A sending number 3
Printer X got number 2 from Producer A
Printer Y got number 2 from Producer A
Producer B sending number 3
Printer Y got number 2 from Producer B
Printer X got number 2 from Producer B
Printer Y got number 3 from Producer A
Printer X got number 3 from Producer A
Printer X got number 3 from Producer B
Printer Y got number 3 from Producer B
```

`idiokit.send` is considered a success when at least *one* party has consumed it with e.g. `idiokit.next`.


## Forks

```python
import idiokit


@idiokit.stream
def produce_numbers(count):
    for number in range(1, count + 1):
        print "Sending number", number
        yield idiokit.send(number)


@idiokit.stream
def print_numbers():
    while True:
        number = yield idiokit.next()
        if number > 5:
            raise ValueError("can't handle numbers larger than 5")
        print "Received number", number


@idiokit.stream
def main(count):
    producer = produce_numbers(count)
    try:
        yield producer.fork() | print_numbers()
    except ValueError:
        print "Printer crashed!"
        yield producer | idiokit.consume()


idiokit.main_loop(main(10))
```

```console
$ python example.py
Sending number 1
Sending number 2
Received number 1
Sending number 3
Received number 2
Sending number 4
Received number 3
Sending number 5
Received number 4
Sending number 6
Received number 5
Sending number 7
ERROR: Printer crashed!
Sending number 8
Sending number 9
Sending number 10
```
