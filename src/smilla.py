#!/usr/bin/python
# -*- encoding: utf-8 -*-

"""
smilla is a Milter. It encrypts messages to recipients, who publish their
Key in DNS.
Copyright (C) 2015, sys4 AG

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

# Thanks for parts from openpgp-milter found on Github!

__author__ = "Christian Roessner <c@roessner.co>"
__version__ = "0.1"
__copyright_ = "AGPL"

import os
import sys
import email
import unbound
import ConfigParser
import pwd
import grp
import signal
import Milter

from threading import Thread
from syslog import syslog, openlog, LOG_PID, LOG_NOTICE, LOG_ERR, LOG_MAIL
from decorator import decorator
from ConfigParser import NoOptionError, NoSectionError
from cStringIO import StringIO
from hashlib import sha224
from M2Crypto import BIO, SMIME, X509

try:
    import setproctitle
    setproctitle.setproctitle("smilla")
except:
    pass


NAME = "smilla"
ANCHOR = "/etc/unbound/dnssec/root-anchors.txt"
CFG_FILE = "/etc/%s.cfg" % NAME
SMIMEA = 65226
CIPHER="aes_256_cbc"

DEBUG = False


@decorator
def nonetype(f, *p, **kw):
    try:
        result = f(*p, **kw)
    except TypeError:
        result = None
    except NoOptionError:
        result = None
    except NoSectionError:
        result = None
    return result


class Config(ConfigParser.RawConfigParser):
    def __init__(self):
        ConfigParser.RawConfigParser.__init__(self)

        self.__user = None
        self.__group = None
        self.__bind_address = None
        self.__bind_address6 = None
        self.__port = None
        self.__pidfile = None
        self.__randfile = None
        self.__delimiter = None
        self.__trust_anchor = None
        self.__milter_timeout = None

        self._read_config()

    @nonetype
    def _get_section_str(self, sec, val):
        return self.get(sec, val)

    @nonetype
    def _get_section_int(self, sec, val):
        return self.getint(sec, val)

    def _read_config(self):
        cfg_file_ok = True
        if os.path.exists(CFG_FILE):
            self.read(CFG_FILE)
        else:
            print >> sys.stderr, ("No configuration file available")
            cfg_file_ok = False

        if cfg_file_ok:
            self.__user = self._get_section_str("config", "user")
            self.__group = self._get_section_str("config", "group")
            self.__bind_address = self._get_section_str("config",
                                                        "bind_address")
            self.__bind_address6 = self._get_section_str("config",
                                                         "bind_address6")
            self.__port = self._get_section_int("config", "port")
            self.__pidfile = self._get_section_str("config", "pidfile")
            self.__delimiter = self._get_section_str("config", "delimiter")
            self.__trust_anchor = self._get_section_str("config",
                                                        "trust_anchor")
            self.__milter_timeout = self._get_section_int("config",
                                                          "milter_timeout")

        if self.__user in ("", None):
            self.__user = "milter"
        if self.__group in ("", None):
            self.__group = "milter"
        if self.__port in ("", None):
            self.__port = 10489
        if self.__bind_address in ("", None) and \
                        self.__bind_address6 in ("", None):
            self.__bind_address = "127.0.0.1"
        if self.__bind_address is not None and \
                        self.__bind_address6 is not None:
            print >> sys.stderr, "Do not specify bind_address and " \
                                 "bind_address6 at the same time! Aborting"
            sys.exit(os.EX_CONFIG)
        if self.__bind_address is not None:
            self.__socketname = "inet:%s@%s" % (self.__port,
                                                self.__bind_address)
        else:
            self.__socketname = "inet6:%s@[%s]" % (self.__port,
                                                self.__bind_address6)
        if self.__pidfile in ("", None):
            self.__pidfile = "/run/%s/%s.pid" % (NAME, NAME)
        if self.__delimiter in ("", None):
            self.__delimiter = "+"
        if self.__trust_anchor in ("", None):
            self.__trust_anchor = ANCHOR
        if self.__milter_timeout in ("", None):
            self.__milter_timeout = 300

    @property
    def user(self):
        return self.__user

    @property
    def group(self):
        return self.__group

    @property
    def bind_address(self):
        return self.__bindaddress

    @property
    def bind_address6(self):
        return self.__bindaddress6

    @property
    def port(self):
        return self.__port

    @property
    def pidfile(self):
        return self.__pidfile

    @property
    def delimiter(self):
        return self.__delimiter

    @property
    def trust_anchor(self):
        return self.__trust_anchor

    @property
    def milter_timeout(self):
        return self.__milter_timeout

    @property
    def socketname(self):
        return self.__socketname


class Smilla(Milter.Base):
    def __init__(self):
        self.__id = Milter.uniqueID()
        self.__ipname = None
        self.__ip = None
        self.__port = None

    @Milter.noreply
    def connect(self, ipname, family, hostaddr):
        self.__ip = hostaddr[0]
        self.__ipname = ipname
        self.__port = hostaddr[1]

        syslog("connect from %s[%s]:%s" % (self.__ipname,
                                           self.__ip,
                                           self.__port))

        return Milter.CONTINUE

    @Milter.noreply
    def envfrom(self, mailfrom, *mstr):
        self.__mailfrom = mailfrom
        self.__msg_body = list()
        self.__fp = StringIO()

        return Milter.CONTINUE

    @Milter.noreply
    def header(self, name, hval):
        self.__fp.write('%s: %s\r\n' % (name, hval))

        return Milter.CONTINUE

    @Milter.noreply
    def body(self, chunk):
        self.__msg_body.append(chunk)

        return Milter.CONTINUE

    def eom(self):
        global ctx  # unbound

        self.__fp.seek(0)

        smime = SMIME.SMIME()
        cert_stack = X509.X509_Stack()

        msg = email.message_from_file(self.__fp)

        # get recipients from email message
        tos = msg.get_all('to', list())
        ccs = msg.get_all('cc', list())
        all_recipients = email.utils.getaddresses(tos + ccs)
        recipients = list()
        for entry in all_recipients:
            recipients.append(entry[1])

        for recipient in iter(recipients):
            # Normalize the recipient. This breaks RFC822
            recipient = recipient.lower()
            recipient = recipient.split(cfg.delimiter)[0]

            username, domainname = recipient.split('@')
            rfcname = sha224(username).hexdigest()
            query_name = '%s._smimecert.%s' % (rfcname, domainname)
            status, result = ctx.resolve(query_name, SMIMEA,
                    unbound.RR_CLASS_IN)
            if status != 0:
                syslog(LOG_ERR,
                       "unbound SMIMEA lookup for '%s' "
                      "returned non-zero status, deferring" % recipient)
                return Milter.TEMPFAIL
            if result.rcode_str == 'serv fail':
                syslog(LOG_ERR,
                       "unbound SMIMEA lookup for '%s' "
                      "returned SERVFAIL, deferring" % recipient)
                return Milter.TEMPFAIL
            if result.bogus:
                syslog(LOG_ERR,
                       "unbound SMIMEA lookup for '%s' "
                      "returned with INVALID DNSSEC data, deferring"
                      % recipient)
                return Milter.TEMPFAIL
            if not result.secure:
                syslog(LOG_ERR,
                       "unbound SMIMEA lookup for '%s' "
                      "ignored as the domain is not signed with DNSSEC "
                      "- letting go plaintext" % recipient)
                return Milter.CONTINUE
            if not result.havedata:
                syslog(LOG_ERR,
                       "unbound SMIMEA lookup for '%s' "
                      "succeeded but no OpenPGP key publishd - letting go "
                      "plaintext"
                      % recipient)
                return Milter.CONTINUE

            f = StringIO(result.data.raw[0])

            cert_usage_field = ord(f.read(1))
            selector = ord(f.read(1))
            cert_association_data = ord(f.read(1))

            fail = False
            if cert_usage_field == 0x01 or cert_usage_field == 0x03:
                if selector == cert_association_data == 0x00:
                    der = ""
                    while True:
                        data = f.read(1024)
                        if data == "":
                            break
                        der += data
                    cert_stack.push(X509.load_cert_der_string(der))
                else:
                    fail = True
            else:
                fail = True

            if fail:
                syslog(LOG_ERR, "Incorrect DNS data for %s" % recipient)
                return Milter.CONTINUE

        smime.set_x509_stack(cert_stack)
        smime.set_cipher(SMIME.Cipher(CIPHER))
        msg_buf = BIO.MemoryBuffer()
        msg_body = "".join(self.__msg_body)
        # We need to replace line endings
        msg_body = "\n".join(msg_body.split("\r\n"))
        msg = email.message_from_string(msg_body)
        if not msg.is_multipart():
            if "Content-Type" in msg:
                prefix = "Content-Type: %s\n" % msg["Content-Type"]
            else:
                prefix = "Content-Type: text/plain\n"
            if "Content-Disposition" in msg:
                prefix += "Content-Disposition: %s\n" % msg[
                    "Content-Disposition"]
            if "Content-Transfer-Encoding" in msg:
                prefix += "Content-Transfer-Encoding: %s\n" % msg[
                    "Content-Transfer-Encoding"]
            prefix += "\n"
        else:
            prefix = ""
        msg_buf.write(prefix + msg_body)
        p7 = smime.encrypt(msg_buf)

        out = BIO.MemoryBuffer()
        smime.write(out, p7)
        out.close()

        # "out" contains header and body. Need to split things
        while True:
            line = out.readline()
            if line == "\n":
                break
            line.strip()
            name, hval = line.split(":")
            hval = hval.strip()
            if name == "MIME-Version" and "MIME-Version" in msg:
                continue
            if name == "Content-Disposition" and "Content-Disposition" in msg:
                self.chgheader(name, 1, hval)
                continue
            if name == "Content-Type" and "Content-Type" in msg:
                self.chgheader(name, 1, hval)
                continue
            if name == "Content-Transfer-Encoding" and \
                    "Content-Transfer-Encoding" in msg:
                self.chgheader(name, 1, hval)
                continue
            self.addheader(name, hval)

        self.replacebody(out.read())

        self.addheader('X-SMIMEA', 'Message has been encrypted' , 1)

        return Milter.CONTINUE

    def close(self):
        syslog("disconnect from %s[%s]:%s" % (self.__ipname,
                                              self.__ip,
                                              self.__port))

        return Milter.CONTINUE

    def abort(self):
        return Milter.CONTINUE


cfg = Config()

ctx = unbound.ub_ctx()
ctx.resolvconf('/etc/resolv.conf')
try:
    if os.path.isfile(cfg.trust_anchor):
       ctx.add_ta_file(cfg.trust_anchor)
except:
    pass


def runner():
    """Starts the milter loop"""

    Milter.factory = Smilla

    flags = Milter.CHGBODY + Milter.CHGHDRS + Milter.ADDHDRS
    Milter.set_flags(flags)

    Milter.runmilter(NAME, cfg.socketname, timeout=cfg.milter_timeout)


def main():
    openlog(NAME, LOG_PID, LOG_MAIL)

    uid = pwd.getpwnam(cfg.user)[2]
    gid = grp.getgrnam(cfg.group)[2]

    try:
        os.setgid(gid)
    except OSError, e:
        print >> sys.stderr, ('Could not set effective group id: %s' % str(e))
        sys.exit(os.EX_OSERR)
    try:
        os.setuid(uid)
    except OSError, e:
        print >> sys.stderr, ('Could not set effective user id: %s' % str(e))
        sys.exit(os.EX_OSERR)

    if not DEBUG:
        try:
            pid = os.fork()
        except OSError, e:
            print >> sys.stderr, ("First fork failed: (%d) %s"
                                  % (e.errno, e.strerror))
            sys.exit(os.EX_OSERR)
        if (pid == 0):
            os.setsid()
            try:
                pid = os.fork()
            except OSError, e:
                print >> sys.stderr, ("Second fork failed: (%d) %s"
                                      % (e.errno, e.strerror))
                sys.exit(os.EX_OSERR)
            if (pid == 0):
                os.chdir("/")
                os.umask(0)
            else:
                os._exit(0)
        else:
            os._exit(0)

        sys.stdin = file(os.devnull, "r")
        sys.stdout = file(os.devnull, "w")
        sys.stderr = file(os.devnull, "w")

    try:
        if cfg.pidfile is not None:
            with open(cfg.pidfile, "w") as fd:
                fd.write(str(os.getpid()))
    except IOError, e:
        syslog(LOG_ERR, "Can not create pid file: %s" % str(e))

    def finish(signum, frame):
        syslog(LOG_NOTICE,
               "%s-%s milter shutdown. Caught signal %d"
               % (NAME, __version__, signum))

    signal.signal(signal.SIGINT, finish)
    signal.signal(signal.SIGQUIT, finish)
    signal.signal(signal.SIGTERM, finish)

    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    signal.siginterrupt(signal.SIGHUP, False)
    signal.siginterrupt(signal.SIGUSR1, False)

    syslog(LOG_NOTICE, "%s-%s milter startup" % (NAME, __version__))

    milter_t = Thread(target=runner)
    milter_t.daemon = True
    milter_t.start()

    signal.pause()

    try:
        if cfg.pidfile is not None and os.path.exists(cfg.pidfile):
            os.unlink(cfg.pidfile)
    except IOError, e:
        syslog(LOG_ERR, "Can not remove pid file: %s" % str(e))
        sys.exit(os.EX_OSERR)

    sys.exit(os.EX_OK)


if __name__ == "__main__":
    main()
    sys.exit(os.EX_OK)