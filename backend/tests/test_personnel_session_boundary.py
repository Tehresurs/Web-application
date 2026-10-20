"""No account fixtures: genuine session checks must reject anonymous HR calls."""
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from starlette.requests import Request
from app.api import personnel_transfers as api
from app.services.user_auth import AuthService


class PersonnelSessionBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def deny_connection():
            raise AssertionError('This suite must not connect to any database')
        cls.auth = AuthService(connection_factory=deny_connection)

    def request(self, origin='http://127.0.0.1:8001', peer='127.0.0.1'):
        headers = [(b'host', b'127.0.0.1:8001')]
        if origin is not None:
            headers.append((b'origin', origin.encode()))
        return Request(dict(type='http', method='POST', scheme='http',
            path='/api/employees/1/position-transfers', query_string=b'',
            server=('127.0.0.1', 8001), client=(peer, 12345), headers=headers))

    def rejected(self, action, status):
        with patch.object(api.user_auth, 'service', return_value=self.auth), \
             patch.object(api.repository, 'capabilities', side_effect=AssertionError('Authorization must run first')):
            with self.assertRaises(HTTPException) as caught:
                action()
        self.assertEqual(caught.exception.status_code, status)

    def test_read_requires_session(self):
        self.rejected(lambda: api.session(self.request()), 401)

    def test_write_requires_session(self):
        self.rejected(lambda: api.session(self.request(), True), 403)

    def test_acting_and_completion_require_session(self):
        self.rejected(lambda: api.acting_writer(self.request()), 403)

    def test_review_requires_session(self):
        self.rejected(lambda: api.acting_writer(self.request(), review=True), 403)

    def test_missing_or_foreign_origin_rejected(self):
        for origin in (None, 'http://example.invalid'):
            with self.subTest(origin=origin):
                self.rejected(lambda: api.session(self.request(origin), True), 403)

    def test_remote_http_rejected(self):
        self.rejected(lambda: api.session(self.request(peer='192.0.2.1'), True), 403)


if __name__ == '__main__':
    unittest.main()
