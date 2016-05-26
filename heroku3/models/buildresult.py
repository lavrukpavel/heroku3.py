from . import BaseResource
from .line import Line

class BuildResult(BaseResource):
    _arrays = { 'lines': Line }

    def __repr__(self):
        return "<buildresult>"
