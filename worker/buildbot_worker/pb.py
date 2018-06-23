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

from twisted.application import internet
from twisted.application import service
from twisted.cred import credentials
from twisted.internet import error
from twisted.internet import reactor
from twisted.python import log
from twisted.spread import pb

from buildbot_worker.base import BotBase
from buildbot_worker.base import ConnectingWorkerBase
from buildbot_worker.base import WorkerForBuilderBase
from buildbot_worker.pbutil import ReconnectingPBClientFactory
from buildbot_worker.util import HangCheckFactory


class UnknownCommand(pb.Error):
    pass


class WorkerForBuilderPb(WorkerForBuilderBase, pb.Referenceable):
    pass


class BotPb(BotBase, pb.Referenceable):
    WorkerForBuilder = WorkerForBuilderPb


class BotFactory(ReconnectingPBClientFactory):
    # 'keepaliveInterval' serves two purposes. The first is to keep the
    # connection alive: it guarantees that there will be at least some
    # traffic once every 'keepaliveInterval' seconds, which may help keep an
    # interposed NAT gateway from dropping the address mapping because it
    # thinks the connection has been abandoned.  This also gives the operating
    # system a chance to notice that the master has gone away, and inform us
    # of such (although this could take several minutes).
    keepaliveInterval = None  # None = do not use keepalives

    # 'maxDelay' determines the maximum amount of time the worker will wait
    # between connection retries
    maxDelay = 300

    keepaliveTimer = None
    unsafeTracebacks = 1
    perspective = None

    # for tests
    _reactor = reactor

    def __init__(self, buildmaster_host, port, keepaliveInterval, maxDelay,
                 maxRetries=None, maxRetriesCallback=None):
        ReconnectingPBClientFactory.__init__(self)
        self.maxDelay = maxDelay
        self.keepaliveInterval = keepaliveInterval
        # NOTE: this class does not actually make the TCP connections - this information is
        # only here to print useful error messages
        self.buildmaster_host = buildmaster_host
        self.port = port
        self.maxRetries = maxRetries
        self.maxRetriesCallback = maxRetriesCallback

    def retry(self, connector=None):
        ReconnectingPBClientFactory.retry(self, connector=connector)
        log.msg("Retry attempt {}/{}".format(
            self.retries, self.maxRetries if self.maxRetries is not None else "inf"))
        if self.maxRetries is not None and self.retries > self.maxRetries and self.maxRetriesCallback:
            log.msg("Giving up retrying!")
            self.maxRetriesCallback()

    def startedConnecting(self, connector):
        log.msg("Connecting to {0}:{1}".format(self.buildmaster_host, self.port))
        ReconnectingPBClientFactory.startedConnecting(self, connector)
        self.connector = connector

    def gotPerspective(self, perspective):
        log.msg("Connected to {0}:{1}; worker is ready".format(
                self.buildmaster_host, self.port))
        ReconnectingPBClientFactory.gotPerspective(self, perspective)
        self.perspective = perspective
        try:
            perspective.broker.transport.setTcpKeepAlive(1)
        except Exception:
            log.msg("unable to set SO_KEEPALIVE")
            if not self.keepaliveInterval:
                self.keepaliveInterval = 10 * 60
        self.activity()
        if self.keepaliveInterval:
            log.msg("sending application-level keepalives every {0} seconds".format(
                    self.keepaliveInterval))
            self.startTimers()

    def clientConnectionFailed(self, connector, reason):
        self.connector = None
        why = reason
        if reason.check(error.ConnectionRefusedError):
            why = "Connection Refused"
        log.msg("Connection to {0}:{1} failed: {2}".format(
                self.buildmaster_host, self.port, why))
        ReconnectingPBClientFactory.clientConnectionFailed(self,
                                                           connector, reason)

    def clientConnectionLost(self, connector, reason):
        log.msg("Lost connection to {0}:{1}".format(
                self.buildmaster_host, self.port))
        self.connector = None
        self.stopTimers()
        self.perspective = None
        ReconnectingPBClientFactory.clientConnectionLost(self,
                                                         connector, reason)

    def startTimers(self):
        assert self.keepaliveInterval
        assert not self.keepaliveTimer

        def doKeepalive():
            self.keepaliveTimer = None
            self.startTimers()

            # Send the keepalive request.  If an error occurs
            # was already dropped, so just log and ignore.
            log.msg("sending app-level keepalive")
            d = self.perspective.callRemote("keepalive")
            d.addErrback(log.err, "error sending keepalive")
        self.keepaliveTimer = self._reactor.callLater(self.keepaliveInterval,
                                                      doKeepalive)

    def stopTimers(self):
        if self.keepaliveTimer:
            self.keepaliveTimer.cancel()
            self.keepaliveTimer = None

    def activity(self, res=None):
        """Subclass or monkey-patch this method to be alerted whenever there is
        active communication between the master and worker."""
        pass

    def stopFactory(self):
        ReconnectingPBClientFactory.stopFactory(self)
        self.stopTimers()


class Worker(ConnectingWorkerBase, service.MultiService):
    Bot = BotPb

    def __init__(self, buildmaster_host, port, name, passwd, basedir,
                 keepalive, usePTY=None, keepaliveTimeout=None, umask=None,
                 maxdelay=300, numcpus=None, unicode_encoding=None,
                 allow_shutdown=None, maxRetries=None):

        # note: keepaliveTimeout is ignored, but preserved here for
        # backward-compatibility

        assert usePTY is None, "worker-side usePTY is not supported anymore"

        # Store host and port into a tuple. It will be passed straight to other
        # methods and not inspected at all.
        buildmaster = buildmaster_host, port
        ConnectingWorkerBase.__init__(
            self, buildmaster, name, passwd, basedir, keepalive, umask,
            maxdelay, numcpus, unicode_encoding, allow_shutdown, maxRetries)

    def _openConnection(self, buildmaster, name, passwd, keepalive, maxdelay):
        buildmaster_host, port = buildmaster
        bf = self.bf = BotFactory(buildmaster_host, port, keepalive, maxdelay,
            maxRetries=self.maxRetries, maxRetriesCallback=self.gracefulShutdown)
        bf.startLogin(
            credentials.UsernamePassword(name, passwd), client=self.bot)
        self.connection = c = internet.TCPClient(
            buildmaster_host, port,
            HangCheckFactory(bf, hung_callback=self._hung_connection))
        c.setServiceParent(self)

    def _hung_connection(self):
        log.msg("connection attempt timed out (is the port number correct?)")
        if self.maxRetries is not None:
            self.gracefulShutdown()

    def _closeConnection(self):
        self.bf.continueTrying = 0
        self.bf.stopTrying()

    def _hasActiveConnection(self):
        return self.bf.perspective

    def _shutdownConnection(self):
        return self.bf.perspective.callRemote("shutdown")
