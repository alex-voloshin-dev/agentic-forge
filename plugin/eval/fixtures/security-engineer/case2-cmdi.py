"""Backup helper (security review fixture: command injection + secret logged)."""

import logging
import os

log = logging.getLogger("backup")


def run_backup(request, api_token):
    target = request.query["path"]  # user-supplied, untrusted
    # Vulnerability: untrusted input passed straight to the shell.
    os.system("tar czf backup.tgz " + target)
    # Vulnerability: secret written to logs.
    log.info("backup done using token %s", api_token)
