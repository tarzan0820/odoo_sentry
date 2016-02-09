# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo - Sentry connector
#    Copyright (C) 2014 Mohammed Barsi
#    Copyright (C) 2015 Naglis Jonaitis
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging
import sys

import openerp.service.wsgi_server
import openerp.addons.web.controllers.main
import openerp.addons.report.controllers.main
import openerp.http
import openerp.tools.config as config
import openerp.osv.osv
import openerp.exceptions
import openerp.loglevels
from openerp.http import request
from raven import Client
from raven.handlers.logging import SentryHandler
from raven.middleware import Sentry
from raven.conf import setup_logging, EXCLUDE_LOGGER_DEFAULTS


_logger = logging.getLogger(__name__)
ORM_EXCEPTIONS = (
    openerp.osv.osv.except_osv,
    openerp.exceptions.Warning,
    openerp.exceptions.AccessError,
    openerp.exceptions.AccessDenied,
)

LOGLEVELS = dict([
    (getattr(openerp.loglevels, 'LOG_%s' % x), getattr(logging, x))
    for x in ('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET')
])

CLIENT_DSN = config.get('sentry_client_dsn', '').strip()
ENABLE_LOGGING = config.get('sentry_enable_logging', False)
ALLOW_ORM_WARNING = config.get('sentry_allow_orm_warning', False)
INCLUDE_USER_CONTEXT = config.get('sentry_include_context', False)
LOGGING_LEVEL = config.get('sentry_logging_level', 'warn')


def get_user_context():
    """Get the current user context, if possible."""
    cxt = {}
    try:
        session = getattr(request, 'session', {})
    except RuntimeError:
        pass
    else:
        cxt.update({
            'session': {
                'context': session.get('context', {}),
                'db': session.get('db', None),
                'login': session.get('login', None),
                'uid': session.get('uid', None),
            },
        })
    finally:
        return cxt


def serialize_exception(e):
    '''
        overrides `openerp.http.serialize_exception`
        in order to log ORM exceptions.
    '''
    if isinstance(e, ORM_EXCEPTIONS):
        if INCLUDE_USER_CONTEXT:
            client.extra_context(get_user_context())
        if ALLOW_ORM_WARNING:
            client.captureException(sys.exc_info())
        return openerp.http.serialize_exception(e)
    elif isinstance(e, Exception):
        if INCLUDE_USER_CONTEXT:
            client.extra_context(get_user_context())
            client.captureException(sys.exc_info())
    return openerp.http.serialize_exception(e)


class ContextSentryHandler(SentryHandler):

    def __init__(self, allow_orm=False, *args, **kwargs):
        super(ContextSentryHandler, self).__init__(*args, **kwargs)
        self.allow_orm = allow_orm

    def emit(self, rec):
        if not self.allow_orm and isinstance(rec.exc_info, (list, tuple)) and \
                len(rec.exc_info) >= 2:
            # Ignore ORM exceptions
            if isinstance(rec.exc_info[1], ORM_EXCEPTIONS):
                return

        if INCLUDE_USER_CONTEXT:
            client.extra_context(get_user_context())
        super(ContextSentryHandler, self).emit(rec)

if CLIENT_DSN:
    client = Client(CLIENT_DSN)
    
    if LOGGING_LEVEL not in LOGLEVELS:
        LOGGING_LEVEL = 'warn'
    
    if ENABLE_LOGGING:
        # future enhancement: add exclude loggers option
        EXCLUDE_LOGGER_DEFAULTS += ('werkzeug',)
        handler = ContextSentryHandler(
            client=client, level=LOGLEVELS[LOGGING_LEVEL],
            allow_orm=ALLOW_ORM_WARNING)
        setup_logging(handler, exclude=EXCLUDE_LOGGER_DEFAULTS)
    
    if ALLOW_ORM_WARNING:
        openerp.addons.web.controllers.main._serialize_exception = \
            serialize_exception
        openerp.addons.report.controllers.main._serialize_exception = \
            serialize_exception
    
    # wrap the main wsgi app
    openerp.service.wsgi_server.application = Sentry(
        openerp.service.wsgi_server.application, client=client)
    
    if INCLUDE_USER_CONTEXT:
        client.extra_context(get_user_context())
    # Fire the first message
    client.captureMessage('Starting Odoo Server')
