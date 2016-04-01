from .  import BaseResource


class Slug(BaseResource):
    _strs = ['commit', 'commit_description', 'id']
    _ints = []
    _dates = ['created_at', 'updated_at']
    _dicts = ['blob']
    _map = {}
    _pks = ['id']
    order_by = 'created_at'

    def __init__(self):
        self.app = None
        super(Slug, self).__init__()

    def __repr__(self):
        return "<slug '{0} {1}'>\n".format(self.created_at, self.commit_description)
