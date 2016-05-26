from . import BaseResource

class Line(BaseResource):
    _strs  = ['stream', 'line']

    def __repr__(self):
        return "{}: {}".format(self.stream, self.line)
