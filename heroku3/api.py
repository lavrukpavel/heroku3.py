# -*- coding: utf-8 -*-

u"""
heroku3.api
~~~~~~~~~~

This module provides the basic API interface for Heroku.
"""

from __future__ import absolute_import
from .compat import json
from .helpers import is_collection
from .models import Plan, RateLimit
from .models.app import App
from .models.addon import Addon
from .models.dyno import Dyno
from .models.account import Account
from .models.key import Key
from .models.invoice import Invoice
from .models.configvars import ConfigVars
from .models.logsession import LogSession
from .models.oauth import OAuthClient, OAuthAuthorization, OAuthToken
from .rendezvous import Rendezvous
from .structures import KeyedListResource, SSHKeyListResource
from .models.account.feature import AccountFeature
from requests.exceptions import HTTPError
from pprint import pprint # noqa
import requests
from urllib2 import Request, urlopen
from urllib import urlencode
import sys
from itertools import imap

if sys.version_info > (3, 0):
    from urllib import quote
else:
    from urllib import quote # noqa


HEROKU_URL = u'https://api.heroku.com'
HEROKU_ALPHA_URL = u'https://dashboard.heroku.com'


class RateLimitExceeded(Exception):
    pass


class MaxRangeExceeded(Exception):
    pass


class HerokuCore(object):
    u"""The core Heroku class."""
    def __init__(self, session=None):
        super(HerokuCore, self).__init__()
        if session is None:
            session = requests.session()

        #: The User's API Key.
        self._api_key = None
        self._api_key_verified = None
        self._heroku_url = HEROKU_URL
        self._session = session
        self._ratelimit_remaining = None
        self._last_request_id = None

        # We only want JSON back.
        #self._session.headers.update({'Accept': 'application/json'})
        self._session.headers.update({u'Accept': u'application/vnd.heroku+json; version=3', u'Content-Type': u'application/json'})

    def __repr__(self):
        return u'<heroku-core at 0x%x>' % (id(self))

    def authenticate(self, api_key):
        u"""Logs user into Heroku with given api_key."""
        self._api_key = api_key

        # Attach auth to session.
        self._session.auth = (u'', self._api_key)

        return self._verify_api_key()

    @property
    def is_authenticated(self):
        if self._api_key_verified is None:
            return self._verify_api_key()
        else:
            return self._api_key_verified

    def _verify_api_key(self):
        r = self._session.get(self._url_for(u'account/rate-limits'))

        self._api_key_verified = True if r.ok else False

        return self._api_key_verified

    def _url_for(self, *args):
        args = list(imap(unicode, args))
        return u'/'.join([self._heroku_url] + list(args))

    @staticmethod
    def _resource_serialize(o):
        u"""Returns JSON serialization of given object."""
        return json.dumps(o)

    @staticmethod
    def _resource_deserialize(s):
        u"""Returns dict deserialization of a given JSON string."""

        try:
            return json.loads(s)
        except ValueError:
            raise ResponseError(u'The API Response was not valid.')

    def _get_headers_for_request(self, method, url, legacy=False, order_by=None, limit=None, valrange=None, sort=None):
        headers = {}
        if legacy is True:
            #Nasty patch session to fallback to old api
            headers.update({u'Accept': u'application/json'})

        else:
            range_str = None
            if order_by or limit or valrange or sort:
                range_str = u""
                if order_by:
                    range_str = u"{0} ..".format(order_by)
                if limit:
                    if limit > 1000:
                        raise MaxRangeExceeded(u"Your *limit* ({0}) argument is greater than the maximum allowed value of 1000".format(limit))
                    range_str += u"; max={0}".format(limit)
                if not sort is None:
                    assert(sort == u'asc' or sort == u'desc')
                    range_str += u"; order={0}".format(sort)

                if valrange:
                    #If given, This should override limit and order_by
                    range_str = valrange

            if not range_str == None:
                headers.update({u'Range': range_str})

        return headers

    def _http_resource(self, method, resource, params=None, data=None, legacy=False, order_by=None, limit=None, valrange=None, sort=None):
        u"""Makes an HTTP request."""

        if not is_collection(resource):
            resource = [resource]

        url = self._url_for(*resource)

        headers = self._get_headers_for_request(method, url, legacy=legacy, order_by=order_by, limit=limit, valrange=valrange, sort=sort)

        #print "\n\n\n\n"
        #print url
        r = self._session.request(method, url, params=params, data=data, headers=headers)

        if u'ratelimit-remaining' in r.headers:
            self._ratelimit_remaining = r.headers[u'ratelimit-remaining']

        if u'Request-Id' in r.headers:
            self._last_request_id = r.headers[u'Request-Id']

        #if 'Accept-Ranges' in r.headers:
            #print "Accept-Ranges = {0}".format(r.headers['Accept-Ranges'])

        if r.status_code == 422:
            http_error = HTTPError(u'%s - %s Client Error: %s' %
                                   (self._last_request_id, r.status_code, r.content.decode(u"utf-8")))
            http_error.response = r
            raise http_error

        if r.status_code == 429:
            #Rate limit reached
            raise RateLimitExceeded(u"You have exceeded your rate limit \n{0}".format(r.content.decode(u"utf-8")))

        if (not unicode(r.status_code).startswith(u'2')) and (not r.status_code in [304]):
            pass
        r.raise_for_status()
        #print r.content.decode("utf-8")
        #print "\n\n\n\n"
        return r

    def _get_resource(self, resource, obj, params=None, **kwargs):
        u"""Returns a mapped object from an HTTP resource."""
        r = self._http_resource(u'GET', resource, params=params)

        return self._process_item(self._resource_deserialize(r.content.decode(u"utf-8")), obj, **kwargs)

    def _process_item(self, item, obj, **kwargs):

        return obj.new_from_dict(item, h=self, **kwargs)

    def _get_resources(self, resource, obj, params=None, map=None, legacy=None, order_by=None, limit=None, valrange=None, sort=None, **kwargs):
        u"""Returns a list of mapped objects from an HTTP resource."""
        if not order_by:
            order_by = obj.order_by

        return self._process_items(self._get_data(resource, params=params, legacy=legacy, order_by=order_by, limit=limit, valrange=valrange, sort=sort), obj, map=map, **kwargs)

    def _get_data(self, resource, params=None, legacy=None, order_by=None, limit=None, valrange=None, sort=None):

        r = self._http_resource(u'GET', resource, params=params, legacy=legacy, order_by=order_by, limit=limit, valrange=valrange, sort=sort)

        items = self._resource_deserialize(r.content.decode(u"utf-8"))
        if r.status_code == 206 and u'Next-Range' in r.headers and not limit:
            #We have unexpected chunked response - deal with it
            valrange = r.headers[u'Next-Range']
            print u"Warning Response was chunked, Loading the next Chunk using the following next-range header returned by Heroku '{0}'. WARNING - This breaks randomly depending on your order_by name. I think it's only guarenteed to work with id's - Looks to be a Heroku problem".format(valrange)
            new_items = self._get_data(resource, params=params, legacy=legacy, order_by=order_by, limit=limit, valrange=valrange, sort=sort)
            items.extend(new_items)

        return items

    def _process_items(self, d_items, obj, map=None, **kwargs):

        if not isinstance(d_items, list):
            print u"Warning, Response for '{0}' was of type {1} - I was expecting a 'list'. This could mean the api has changed its response type for this request.".format(obj, type(d_items))
            if isinstance(d_items, dict):
                print u"As it's a dict, I'll try to process it anyway"
                return self._process_item(d_items, obj, **kwargs)

        items = [obj.new_from_dict(item, h=self, **kwargs) for item in d_items]

        if map is None:
            map = KeyedListResource

        list_resource = imap(items=items)
        list_resource._h = self
        list_resource._obj = obj
        list_resource._kwargs = kwargs

        return list_resource

class Heroku(HerokuCore):
    u"""The main Heroku class."""

    def __init__(self, session=None):
        super(Heroku, self).__init__(session=session)

    def __repr__(self):
        return u'<heroku-client at 0x%x>' % (id(self))

    def account(self):
        return self._get_resource((u'account'), Account)

    def addons(self, app_id_or_name, **kwargs):
        return self._get_resources(resource=(u'apps', app_id_or_name, u'addons'), obj=Addon, **kwargs)

    def addon_services(self, id_or_name=None, **kwargs):
        if id_or_name is not None:
            return self._get_resource((u'addon-services/{0}'.format(quote(id_or_name))), Plan)
        else:
            return self._get_resources((u'addon-services'), Plan, **kwargs)

    def apps(self, **kwargs):
        return self._get_resources((u'apps'), App, **kwargs)

    def app(self, id_or_name):
        return self._get_resource((u'apps/{0:s}'.format(id_or_name)), App)

    def create_app(self, name=None, stack_id_or_name=u'cedar', region_id_or_name=None):
        u"""Creates a new app."""

        payload = {}

        if name:
            payload[u'name'] = name

        if stack_id_or_name:
            payload[u'stack'] = stack_id_or_name

        if region_id_or_name:
            payload[u'region'] = region_id_or_name

        try:
            r = self._http_resource(
                method=u'POST',
                resource=(u'apps',),
                data=self._resource_serialize(payload)
            )
            r.raise_for_status()
            item = self._resource_deserialize(r.content.decode(u"utf-8"))
            app = App.new_from_dict(item, h=self)
        except HTTPError, e:
            if u"Name is already taken" in unicode(e):
                print u"Warning - {0:s}".format(e)
                app = self.app(name)
                pass
            else:
                raise e
        return app

    def keys(self, **kwargs):
        return self._get_resources((u'account/keys'), Key, map=SSHKeyListResource, **kwargs)

    def invoices(self,**kwargs):
        return self._get_resources((u'account/invoices'),Invoice)

    def labs(self, **kwargs):
        return self.features(**kwargs)

    def features(self, **kwargs):
        return self._get_resources((u'account/features'), AccountFeature, **kwargs)

    def oauthauthorization(self, oauthauthorization_id):
        return self._get_resource((u'oauth', u'authorizations', oauthauthorization_id), OAuthAuthorization)

    def oauthauthorizations(self, **kwargs):
        return self._get_resources((u'oauth', u'authorizations'), OAuthAuthorization, **kwargs)

    def oauthauthorization_create(self, scope, oauthclient_id=None, description=None):
        u"""
        Creates an OAuthAuthorization
        """

        payload = {u'scope': scope}
        if oauthclient_id:
            payload.update({u'client': oauthclient_id})

        if description:
            payload.update({u'description': description})

        r = self._http_resource(
            method=u'POST',
            resource=(u'oauth', u'authorizations'),
            data=self._h._resource_serialize(payload)
        )
        r.raise_for_status()
        item = self._resource_deserialize(r.content.decode(u"utf-8"))
        return OAuthClient.new_from_dict(item, h=self)

    def oauthauthorization_delete(self, oauthauthorization_id):
        u"""
        Destroys the OAuthAuthorization with oauthauthorization_id
        """
        r = self._http_resource(
            method=u'DELETE',
            resource=(u'oauth', u'authorizations', oauthauthorization_id)
        )
        r.raise_for_status()
        return r.ok

    def oauthclient(self, oauthclient_id):
        return self._get_resource((u'oauth', u'clients', oauthclient_id), OAuthClient)

    def oauthclients(self, **kwargs):
        return self._get_resources((u'oauth', u'clients'), OAuthClient, **kwargs)

    def oauthclient_create(self, name, redirect_uri):
        u"""
        Creates an OAuthClient with the given name and redirect_uri
        """

        payload = {u'name': name, u'redirect_uri': redirect_uri}

        r = self._http_resource(
            method=u'POST',
            resource=(u'oauth', u'clients'),
            data=self._h._resource_serialize(payload)
        )
        r.raise_for_status()
        item = self._resource_deserialize(r.content.decode(u"utf-8"))
        return OAuthClient.new_from_dict(item, h=self)

    def oauthclient_delete(self, oauthclient_id):
        u"""
        Destroys the OAuthClient with id oauthclient_id
        """
        r = self._http_resource(
            method=u'DELETE',
            resource=(u'oauth', u'clients', oauthclient_id)
        )
        r.raise_for_status()
        return r.ok

    def oauthtoken_create(self, client_secret=None, grant_code=None, grant_type=None, refresh_token=None):
        u"""
        Creates an OAuthToken with the given optional parameters
        """

        payload = {}
        grant = {}
        if client_secret:
            payload.update({u'client': {u'secret': client_secret}})

        if grant_code:
            grant.update({u'code': grant_code})

        if grant_type:
            grant.update({u'type': grant_type})

        if refresh_token:
            payload.update({u'refresh_token': {u'token': refresh_token}})

        if grant:
            payload.update({u'grant': grant})

        r = self._http_resource(
            method=u'POST',
            resource=(u'oauth', u'tokens'),
            data=self._h._resource_serialize(payload)
        )
        r.raise_for_status()
        item = self._resource_deserialize(r.content.decode(u"utf-8"))
        return OAuthToken.new_from_dict(item, h=self)

    def run_command_on_app(self, appname, command, size=1, attach=True, printout=True, env=None):
        u"""Run a remote command attach=True if you want to capture the output"""
        if attach:
            attach = True
        payload = {u'command': command, u'attach': attach, u'size': size}

        if env:
            payload[u'env'] = env

        r = self._http_resource(
            method=u'POST',
            resource=(u'apps', appname, u'dynos'),
            data=self._resource_serialize(payload)
        )

        r.raise_for_status()
        item = self._resource_deserialize(r.content.decode(u"utf-8"))
        dyno = Dyno.new_from_dict(item, h=self)

        if attach:
            output = Rendezvous(dyno.attach_url, printout).start()
            return output, dyno
        else:
            return dyno

    @property
    def rate_limit(self):
        return self._get_resource((u'account/rate-limits'), RateLimit)

    def ratelimit_remaining(self):

        if self._ratelimit_remaining is not None:
            return int(self._ratelimit_remaining)
        else:
            self.rate_limit
            return int(self._ratelimit_remaining)

    def stream_app_log(self, app_id_or_name, dyno=None, lines=100, source=None, timeout=False):
        logger = self._app_logger(app_id_or_name, dyno=dyno, lines=lines, source=source, tail=True)

        return logger.stream(timeout=timeout)

    def get_app_log(self, app_id_or_name, dyno=None, lines=100, source=None, timeout=False):
        logger = self._app_logger(app_id_or_name, dyno=dyno, lines=lines, source=source, tail=0)

        return logger.get(timeout=timeout)

    def update_appconfig(self, app_id_or_name, config):
        payload = self._resource_serialize(config)
        r = self._http_resource(
            method=u'PATCH',
            resource=(u'apps', app_id_or_name, u'config-vars'),
            data=payload
        )

        r.raise_for_status()
        item = self._resource_deserialize(r.content.decode(u"utf-8"))
        return ConfigVars.new_from_dict(item, h=self)

    def _app_logger(self, app_id_or_name, dyno=None, lines=100, source=None, tail=0):
        payload = {}
        if dyno:
            payload[u'dyno'] = dyno

        if tail:
            payload[u'tail'] = tail

        if source:
            payload[u'source'] = source

        if lines:
            payload[u'lines'] = lines

        r = self._http_resource(
            method=u'POST',
            resource=(u'apps', app_id_or_name, u'log-sessions'),
            data=self._resource_serialize(payload)
        )

        r.raise_for_status()
        item = self._resource_deserialize(r.content.decode(u"utf-8"))

        return LogSession.new_from_dict(item, h=self, app=self)

    @property
    def last_request_id(self):
        return self._last_request_id

class HerokuAlpha(Heroku):
    _heroku_alpha_url = HEROKU_ALPHA_URL
    u"""The Alpha API Heroku class."""
    def __init__(self, session=None):
        super(HerokuAlpha, self).__init__(session=session)

    def __repr__(self):
        return u'<heroku-alpha-client at 0x%x>' % (id(self))

    @staticmethod
    def _resource_alpha_serialize(o):
        return json.dumps(o).encode(u'utf8')

    def _url_for_alpha(self, *args):
        args = list(imap(unicode, args))
        return u'/'.join([self._heroku_alpha_url] + list(args))

    def _get_headers_for_alpha_request(self, method, url, legacy=False, order_by=None, limit=None, valrange=None, sort=None):
        headers = super(HerokuAlpha, self)._get_headers_for_request(method, url, legacy, order_by, limit, valrange, sort)
        headers.update({u'Authorization': u'Bearer {0}'.format(self._api_key)})
        headers.update({u'Accept': u"application/vnd.heroku+json; version=3"})
        headers.update({u'Content-Type': u'application/json'})
        return headers

    def _http_alpha_resource(self, method, resource, params=None, data=None, legacy=False, order_by=None, limit=None, valrange=None, sort=None):
        u"""Makes an HTTP request."""

        if not is_collection(resource):
            resource = [resource]

        url = self._url_for_alpha(*resource)

        headers = self._get_headers_for_alpha_request(method, url, legacy=legacy, order_by=order_by, limit=limit, valrange=valrange, sort=sort)

        r = requests.request(method, url, params=params, data=data, headers=headers)

        if u'ratelimit-remaining' in r.headers:
            self._ratelimit_remaining = r.headers[u'ratelimit-remaining']

        if u'Request-Id' in r.headers:
            self._last_request_id = r.headers[u'Request-Id']
        if r.status_code == 422:
            http_error = HTTPError(u'%s - %s Client Error: %s' %
                                   (self._last_request_id, r.status_code, r.content.decode(u"utf-8")))
            http_error.response = r
            raise http_error

        if r.status_code == 429:
            raise RateLimitExceeded(u"You have exceeded your rate limit \n{0}".format(r.content.decode(u"utf-8")))

        if (not unicode(r.status_code).startswith(u'2')) and (not r.status_code in [304]):
            pass
        return r

    def connect_github_repo(self, app_id_or_name, repo_name):
        data = {
            u'repo': repo_name
        }
        payload = self._resource_alpha_serialize(data)
        r = self._http_alpha_resource(
            method=u'POST',
            resource=(u'alpha-api', u'github', app_id_or_name, u'link'),
            data=payload
        )
        item = self._resource_deserialize(r.content.decode(u"utf-8"))
        return item[u"id"]

    def enable_github_repo_autodeploy(self, app_id_or_name, repo_name, repo_id, branch_name):
        data = {
            u'auto_deploy': True,
            u'branch': branch_name,
            u'pull_requests': {
                u'auto_deploy': False,
                u'copy_db': False,
                u'enabled': False
            },
            u'repo_name': repo_name,
            u'wait_for_ci': False
        }
        payload = self._resource_alpha_serialize(data)
        r = self._http_alpha_resource(
            method=u'PATCH',
            resource=(u'alpha-api', u'github', app_id_or_name, u'link', repo_id),
            data=payload
        )
        item = self._resource_deserialize(r.content.decode(u"utf-8"))
        return item[u"id"]

    def deploy_github_branch(self, app_id_or_name, branch_name):
        data = {
            u'branch': branch_name,
        }
        payload = self._resource_alpha_serialize(data)
        r = self._http_alpha_resource(
            method=u'POST',
            resource=(u'alpha-api', u'github', app_id_or_name, u'push'),
            data=payload
        )
        item = self._resource_deserialize(r.content.decode(u"utf-8"))
        return item[u"build"][u"id"]


class ResponseError(ValueError):
    u"""The API Response was unexpected."""

