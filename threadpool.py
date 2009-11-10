import threado
import threading
import Queue

class ThreadPool(object):
    def __init__(self, max_threads=10):
        self.max_threads = max_threads

        self.queue = Queue.Queue()
        for i in range(max_threads):
            thread = threading.Thread(target=self._thread)
            thread.setDaemon(True)
            thread.start()

    def _thread(self):
        while True:
            task = self.queue.get(True, None)
            if task is None:
                self.queue.task_done()
                break

            channel, func, args, keys = task
            try:
                result = func(*args, **keys)
            except:
                channel.rethrow()
            else:
                channel.send(result)
            finally:
                self.queue.task_done()

    def run(self, func, *args, **keys):
        channel = threado.Channel()
        self.queue.put((channel, func, args, keys))
        return channel
thread_pool = ThreadPool()

run = thread_pool.run
