# -*- coding: utf-8 -*-

u"""
heroku3.core
~~~~~~~~~~~

This module provides the base entrypoint for heroku3.py.
"""

from __future__ import absolute_import
from .api import Heroku, HerokuAlpha
import requests


def from_key(api_key, session=None, alpha_api=False, **kwargs):
    u"""Returns an authenticated Heroku instance, via API Key."""
    if not session:
        session = requests.session()
    # If I'm being passed an API key then I should use only this api key
    # if trust_env=True then Heroku will silently fallback to netrc authentication

    session.trust_env = False
    if alpha_api:
        h = HerokuAlpha(session=session, **kwargs)
    else:
        h = Heroku(session=session, **kwargs)

    # Login.
    h.authenticate(api_key)

    return h
