import collections
         
class LineBuffer(object):
    def __init__(self):
        self.buffer = list()
        self.pending = collections.deque()

    def feed(self, data=""):
        lines = (data + " ").splitlines()
        for line in lines[:-1]:
            self.buffer.append(line)
            self.pending.append("".join(self.buffer))
            self.buffer = list()

        data = lines[-1][:-1]
        if data:
            self.buffer.append(data)

        while self.pending:
            yield self.pending.popleft()

def guess_encoding(text):
    if isinstance(text, unicode):
        return text

    for encoding in ["ascii", "utf-8", "latin-1"]:
        try:
            return text.decode(encoding)
        except UnicodeDecodeError:
            pass
    return text.decode("ascii", "replace")
