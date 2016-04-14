from . import BaseResource

class Source(BaseResource):
    _dicts = ['source_blob']
 
    def __repr__(self):
        return "<source>"
