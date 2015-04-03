#!/usr/bin/env python

import os
import sys
import base64 as b64
import argparse

def smimea(usage, der):
    cert = []

    c = 0
    with open(der, "rb") as f:
        while True:
            l = f.read(1024)
            if l == "": break

            c += len(l)
            cert.append(l)

    data = b64.b16encode("".join(cert))
    print "\# %i 0%i0000%s" % (c + 3, usage, data)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(epilog="Generate SMIMEA RDATA for DNS")
    parser.add_argument("--usage-field",
                        "-u",
                        default=1,
                        type=int,
                        choices=(1, 3),
                        help="Certificate usage field")
    parser.add_argument("--email",
                        "-e",
                        default="",
                        type=str,
                        help="Create SHA224 LHS for an email address")
    parser.add_argument("--cert",
                        "-c",
                        default="",
                        required=True,
                        help="x509 certificate in DER format")
    
    args = parser.parse_args()

    if not os.path.exists(args.cert):
        print("File not found: '%s'" % args.cert)
        sys.exit(os.EX_USAGE)

    if args.email is not "":
        import hashlib
        local, domain = args.email.split("@")
        print hashlib.sha256(local).hexdigest()[:28*2] + \
                            "._smimecert.%s. IN TYPE65514" % domain,

    smimea(args.usage_field, args.cert)
    sys.exit(os.EX_OK)
