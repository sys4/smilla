Requirements
------------

You need the python bindings for the unbound DNS resolver [1], python-decorator
[2], M2Crypto [3], pyinotify[5] and pymilter [4]

 * [1] http://unbound.net/
 * [2] http://pypi.python.org/pypi/decorator http://code.google.com/p/micheles
 * [3] http://pypi.python.org/pypi/M2Crypto or http://chandlerproject.org/bin/view/Projects/MeTooCrypto
 * [4] http://www.bmsi.com/python/milter.html
 * [5] https://github.com/seb-m/pyinotify/wiki

Debian packages:
```
apt install python-pyinotify python-unbound python-milter \
    python-m2crypto python-decorator
```

Installation
------------

 * Copy src/smilla to /usr/local/sbin
 * Copy conf/smilla.cfg to /etc
 * Adapt the configuration file to your needs

Create the directory /run/smilla (or, if you changed the default, use the
directory that you have specified). Change ownership of this directory to match
the user and group parameter in the configuration-file.

Running the milter
------------------

Simply call smilla from a shell. It automatically will dettach itself and run
as a daemon process.

Postfix
-------

/etc/postfix/main.cf:
```
        ...
	# If running Postfix >= 3.0.0
	smilla = { inet:127.0.0.1:10489,
	           command_timeout=300s,
		   default_action=accept }
	# If running Postfix < 3.0.0
	smilla = inet:127.0.0.1:8894
	smtpd_milters = ..., ${smilla}, ${DKIM_Signing}, ...
	...
```

If you use a DKIM milter, you MUST place smilla in front of this milter!

You can also modify the command_timeout parameter, if 300 seconds are not ok
for your setup. You also need to adopt milter_timeout from smilla as well to
match this value.

