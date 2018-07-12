# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from __future__ import absolute_import
from __future__ import print_function

import json

from autobahn.twisted.websocket import WebSocketClientFactory
from autobahn.twisted.websocket import WebSocketClientProtocol
from twisted.application import service
from twisted.application.internet import ClientService
from twisted.application.internet import backoffPolicy
from twisted.internet import reactor
from twisted.internet.endpoints import clientFromString

from buildbot_worker.base import BotBase
from buildbot_worker.base import ConnectingWorkerBase
from buildbot_worker.compat import unicode2bytes


class Protocol(WebSocketClientProtocol):

    def __init__(self):
        WebSocketClientProtocol.__init__(self)
        self.frame_id = 0

    def onOpen(self):
        self.sendJsonMessage(self.factory.getLogin())

    def onMessage(self, payload, _isBinary):
        pass

    def sendJsonMessage(self, payload, **kwargs):
        payload_copy = {}
        if '_id' not in kwargs:
            payload_copy['_id'] = self.nextId()
        payload_copy.update(payload)
        frame = unicode2bytes(json.dumps(payload_copy))
        self.sendMessage(frame, **kwargs)

    def nextId(self):
        self.frame_id += 1
        if self.frame_id > 10000:
            self.frame_id = 0
        return self.frame_id


class BotFactory(WebSocketClientFactory):

    protocol = Protocol

    def __init__(self, worker):
        WebSocketClientFactory.__init__(self)
        self.worker = worker

    def startLogin(self, username, password):
        self._credentials = username, password

    def getLogin(self):
        login = {
            'cmd': 'worker',
            'action': 'login',
            'username': self._credentials[0],
            'password': self._credentials[1],
        }
        return login


class WebSocketWorker(ConnectingWorkerBase, service.MultiService):
    Bot = BotBase

    def __init__(self, buildmaster, name, passwd, basedir, keepalive,
                 buildmaster_path='/', umask=None, maxdelay=300, numcpus=None,
                 unicode_encoding=None, allow_shutdown=None, maxRetries=None):
        buildmaster_remote = buildmaster, buildmaster_path
        ConnectingWorkerBase.__init__(
            self, buildmaster_remote, name, passwd, basedir, keepalive,
            umask=umask, maxdelay=maxdelay, numcpus=numcpus,
            unicode_encoding=unicode_encoding, allow_shutdown=allow_shutdown,
            maxRetries=maxRetries)

    def _openConnection(self, buildmaster_remote, name, passwd, keepalive, maxdelay):
        buildmaster, buildmaster_path = buildmaster_remote
        endpoint = clientFromString(reactor, buildmaster)
        ws_url = 'ws://%s:%s%s/ws' % (endpoint._host, endpoint._port, buildmaster_path)
        bf = self.bf = BotFactory(self)
        bf.startLogin(name, passwd)
        bf.setSessionParameters(url=ws_url)
        self.connection = c = ClientService(
            endpoint, bf, retryPolicy=backoffPolicy(maxDelay=maxdelay))
        c.setServiceParent(self)

    def _closeConnection(self):
        pass

    def _hasActiveConnection(self):
        return False

    def _shutdownConnection(self):
        pass
