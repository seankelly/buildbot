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

from autobahn.twisted.websocket import WebSocketClientFactory
from autobahn.twisted.websocket import WebSocketClientProtocol
from twisted.application import service
from twisted.application.internet import ClientService
from twisted.internet import reactor
from twisted.internet.endpoints import clientFromString

from buildbot_worker.base import ConnectingWorkerBase


class BotFactory(WebSocketClientFactory):

    protocol = WebSocketClientProtocol


class WebSocketWorker(ConnectingWorkerBase, service.MultiService):

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
        bf = self.bf = BotFactory()
        bf.setSessionParameters(url=ws_url)
        self.connection = c = ClientService(endpoint, bf)
        c.setServiceParent(self)

    def _closeConnection(self):
        pass

    def _hasActiveConnection(self):
        return False

    def _shutdownConnection(self):
        pass
