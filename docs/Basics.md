# idiokit Basics


## Entry Point

In this section you'll learn about:

 * `idiokit.main_loop`: The entry point to idiokit's world. Run your asynchronous main function with this.

 * `idiokit.sleep`: Your first asynchronous function. Similar to `time.sleep` that sleep for the given number of seconds. However `time.sleep` blocks the whole main thread, while `idiokit.sleep` allows idiokit to do other stuff while waiting.

```python
import idiokit

idiokit.main_loop(idiokit.sleep(1.0))
```


## Defining Asynchronous Functions

In this section you learn about:

 * Composing asynchronous functions to more sophisticated ones with `idiokit.stream`.

 * Passing in arguments to asynchronous functions (hint: it's like passing in arguments to any other function).

```python
import idiokit


@idiokit.stream
def count_to_three():
    yield idiokit.sleep(1.0)
    print 1
    yield idiokit.sleep(1.0)
    print 2
    yield idiokit.sleep(1.0)
    print 3


idiokit.main_loop(count_to_three())
```

```console
$ python example.py
1
2
3
```

Passing arguments:

```python
import idiokit


@idiokit.stream
def count_to(count):
    for number in range(1, count + 1):
        yield idiokit.sleep(1.0)
        print number


idiokit.main_loop(count_to(3))
```

Composing your own functions:

```python
import idiokit


@idiokit.stream
def sleep_and_print(number):
    yield idiokit.sleep(1.0)
    print number    


@idiokit.stream
def count_to(count):
    for number in range(1, count + 1):
        yield sleep_and_print(number)


idiokit.main_loop(count_to(3))
```

## Returning Values

In this section you'll learn about:

 * Returning values from asynchronous functions and catching them.

```python
import idiokit


@idiokit.stream
def calculate_square_root(number):
    yield idiokit.sleep(1.0)
    return number ** 0.5


@idiokit.stream
def print_square_roots(*numbers):
    for number in numbers:
        square_root = yield calculate_square_root(number)
        print "Square root of", number, "is", square_root


idiokit.main_loop(print_square_roots(1, 4, 16))
```

```
$ python example.py
Square root of 1 is 1.0
Square root of 4 is 2.0
Square root of 16 is 4.0
```

Yes! Wait, no?

```
$ python example.py
File "example.py", line 7
  return number ** 0.5
SyntaxError: 'return' with argument inside generator
```

Python does not allow `return value` statements inside generators so we must use a workaround called `idiokit.stop`.

```python
import idiokit


@idiokit.stream
def calculate_square_root(number):
    yield idiokit.sleep(1.0)
    idiokit.stop(number ** 0.5)


@idiokit.stream
def print_square_roots(*numbers):
    for number in numbers:
        square_root = yield calculate_square_root(number)
        print "Square root of", number, "is", square_root


idiokit.main_loop(print_square_roots(1, 4, 16))
```

The `idiokit.main_loop` returns the return value of your main function.

```python
import idiokit


@idiokit.stream
def calculate_square_root(number):
    yield idiokit.sleep(1.0)
    return number ** 0.5


square_root = idiokit.main_loop(calculate_square_root(1337))
print "Square root of 1337 is", square_root
```


## Exception Handling

```python
import idiokit


@idiokit.stream
def calculate_square_root(number):
    yield idiokit.sleep(1.0)
    idiokit.stop(number ** 0.5)


@idiokit.stream
def print_square_roots(*numbers):
    for number in numbers:
        square_root = yield calculate_square_root(number)
        print "Square root of", number, "is", square_root


idiokit.main_loop(print_square_roots(1, 4, "a horse"))
```

```console
$ python example.py
Square root of 1 is 1.0
Square root of 4 is 2.0
Traceback (most recent call last):
  File "example.py", line 17, in <module>
    idiokit.main_loop(print_square_roots(1, 4, "a horse"))
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 352, in _next
    next = require_stream(self._gen.throw(*args))
  File "example.py", line 13, in print_square_roots
    square_root = yield calculate_square_root(number)
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 354, in _next
    next = require_stream(self._gen.send(peel_args(args)))
  File "example.py", line 7, in calculate_square_root
    idiokit.stop(number ** 0.5)
TypeError: unsupported operand type(s) for ** or pow(): 'str' and 'float'    
```

```python
import idiokit


@idiokit.stream
def calculate_square_root(number):
    yield idiokit.sleep(1.0)
    idiokit.stop(number ** 0.5)


@idiokit.stream
def print_square_roots(*numbers):
    for value in numbers:
        try:
            square_root = yield calculate_square_root(value)
        except TypeError:
            print "Square root of", value, "is a mystery"
        else:
            print "Square root of", value, "is", square_root


idiokit.main_loop(print_square_roots(1, 4, "a horse"))
```

```console
$ python example.py
Square root of 1 is 1.0
Square root of 4 is 2.0
Square root of a horse is a mystery
```

### Catching Signals: `idiokit.Signal`

```python
import idiokit


@idiokit.stream
def sleep_and_print(number):
    yield idiokit.sleep(1.0)
    print number    


@idiokit.stream
def count_to(count):
    for number in range(1, count + 1):
        yield sleep_and_print(number)


idiokit.main_loop(count_to(1000000))
```

We notice that this might take a while so we press `CTRL + C`:

```console
$ python example.py
1
2
3
^CTraceback (most recent call last):
  File "example.py", line 16, in <module>
    idiokit.main_loop(count_to(1000000))
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 352, in _next
    next = require_stream(self._gen.throw(*args))
  File "example.py", line 13, in count_to
    yield sleep_and_print(number)
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 352, in _next
    next = require_stream(self._gen.throw(*args))
  File "example.py", line 6, in sleep_and_print
    yield idiokit.sleep(1.0)
idiokit.idiokit.Signal: caught signal 2 (SIGINT)
```

Graceful handling:

```python
import idiokit


@idiokit.stream
def sleep_and_print(number):
    yield idiokit.sleep(1.0)
    print number    


@idiokit.stream
def count_to(count):
    try:
        for number in range(1, count + 1):
            yield sleep_and_print(number)
    except idiokit.Signal as signal:
        pass


idiokit.main_loop(count_to(1000000))
```

```
$ python test.py
1
2
3
^C
```
