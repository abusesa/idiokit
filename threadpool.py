from __future__ import with_statement
import threado
import threading
import Queue

class ThreadPool(object):
    def __init__(self, idle_time=5.0):
        self.lock = threading.Lock()
        self.threads = list()
        self.idle_time = idle_time

    @threado.stream
    def run(inner, self, func, *args, **keys):
        with self.lock:
            if self.threads:
                thread, queue = self.threads.pop()
            else:
                queue = Queue.Queue()
                thread = threading.Thread(target=self._thread, args=(queue,))
                thread.setDaemon(True)

        channel = threado.Channel()    
        queue.put((channel, func, args, keys))
        if not thread.isAlive():
            thread.start()

        result = yield channel
        inner.finish(result)

    def _thread(self, queue):
        item = threading.currentThread(), queue

        while True:
            try:
                task = queue.get(True, self.idle_time)
            except Queue.Empty:
                with self.lock:
                    if item not in self.threads:
                        continue
                    self.threads.remove(item)
                    return
            if task is None:
                return

            channel, func, args, keys = task
            try:
                result = func(*args, **keys)
            except:
                self.threads.append(item)
                channel.rethrow()
            else:
                self.threads.append(item)
                channel.finish(result)
thread_pool = ThreadPool()

run = thread_pool.run
