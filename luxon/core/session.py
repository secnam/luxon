# -*- coding: utf-8 -*-
# Copyright (c) 2018 Christiaan Frans Rademan.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holders nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF
# THE POSSIBILITY OF SUCH DAMAGE.

import os
import logging
import pickle
import time
import datetime
import fcntl
import threading

from luxon import g
from luxon.utils.encoding import if_unicode_to_bytes
from luxon.helpers.redis import strict as redis
from luxon.utils.encoding import if_bytes_to_unicode

log = logging.getLogger(__name__)

lock = threading.Lock()


class Session(object):
    """ Session Base Class.

    Neutrino provides full support for anonymous sessions. The session framework
    lets you store and retrieve arbitrary data on a per-site-visitor basis. It
    stores data on the server side and abstracts the sending and receiving of
    cookies. Cookies contain a session ID – not the data itself (unless you’re
    using the cookie based backend).

    SessionBase A dictionary like object containing session data.

    """
    def __init__(self, session_id, backend=None, expire=3600):
        if hasattr(session_id, '__call__'):
            session_id = session_id()

        self._session_id = if_bytes_to_unicode(session_id, 'ISO-8859-1')
        self._session = {}
        if backend is not None:
            self._backend = backend(int(expire), session_id, self._session)
        else:
            self._backend = None

        self.load()

    def save(self):
        if hasattr(self._backend, 'save'):
            self._backend.save()

    def load(self):
        if hasattr(self._backend, 'load'):
            self._backend.load()

    def clear(self):
        if hasattr(self._backend, 'clear'):
            self._backend.clear()

    def get(self, k, d=None):
        return self._session.get(k, d)

    def __setitem__(self, key, value):
        self._session[key] = value

    def __getitem__(self, key):
        return self._session[key]

    def __delitem__(self, key):
        try:
            del self._session[key]
        except KeyError:
            pass

    def __contains__(self, key):
        return key in self._session

    def __iter__(self):
        return iter(self._session)

    def __len__(self):
        return len(self._session)


class SessionRedis(object):
    """Session Redis Interface.

    Used for storing session data in Redis. Helpful when running multiple
    instances of tachyonic which requires a shared session state.

    Please refer to Session.
    """
    def __init__(self, expire, session_id, session):
        self._redis = redis()
        self._expire = expire
        self._session_id = session_id
        self._session = session
        self._name = "session:%s" % (self._session_id,)

    def load(self):
        if self._redis.exists(self._name):
            self._session.update(pickle.loads(self._redis.get(self._name)))

    def save(self):
        if len(self._session) > 0:
            self._redis.set(self._name, pickle.dumps(self._session))
            self._redis.expire(self._name, self._expire)

    def clear(self):
        self._session.clear()
        try:
            self._redis.delete(self._name)
        except Exception:
            pass

class SessionFile(object):
    """ Session File Interface.

    Used for storing session data in flat files.

    Please refer to Session.
    """
    def __init__(self, expire, session_id, session):
        self._path = "%s/tmp/" % g.app_root
        self._expire = expire
        self._session_id = session_id
        self._session = session

    def load(self):
        lock.acquire()
        try:
            if os.path.isfile("%s%s.session" % (self._path, self._session_id,)):
                ts = int(time.mktime(datetime.datetime.now().timetuple()))
                stat = os.stat("%s%s.session" % (self._path, self._session_id))
                lm = int(stat.st_mtime)
                if ts - lm > self._expire:
                    self._session.clear()

            if os.path.isfile("%s%s.session" % (self._path, self._session_id,)):
                h = open("%s%s.session" % (self._path, self._session_id,), 'rb', 0)
                fcntl.flock(h, fcntl.LOCK_EX)
                try:
                    self._session.update(pickle.load(h))
                finally:
                    fcntl.flock(h, fcntl.LOCK_UN)
                    h.close()
            else:
                self._session.clear()
        finally:
            lock.release()

    def save(self):
        lock.acquire()
        h = None
        try:
            h = open("%s%s.session" % (self._path, self._session_id,), 'wb', 0)
            fcntl.flock(h, fcntl.LOCK_EX)
            pickle.dump(self._session, h)
            h.flush()
            fcntl.flock(h, fcntl.LOCK_UN)
        finally:
            if h is not None:
                h.close()
            lock.release()

    def clear(self):
        lock.acquire()
        try:
            self._session.clear()
            try:
                os.unlink("%s%s.session" % (self._path, self._session_id,))
            except Exception:
                pass
        finally:
            lock.release()

def cookie():
    req = g.current_request
    cookie_name = req.host.replace('.', '_')

    if cookie_name in req.cookies:
        session_id = if_bytes_to_unicode(req.cookies[cookie_name],
                                         'ISO-8859-1')
    else:
        session_id = req.id
        req.response.set_cookie(cookie_name, session_id,
                                 domain=req.host)

    return session_id

