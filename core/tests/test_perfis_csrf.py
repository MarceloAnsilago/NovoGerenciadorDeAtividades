import re

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings


@override_settings(CSRF_COOKIE_HTTPONLY=True)
class PerfisCSRFTests(SimpleTestCase):
    def test_form_token_authorizes_password_reset_with_httponly_cookie(self):
        factory = RequestFactory()
        request = factory.get('/perfis/')
        request.user = AnonymousUser()
        html = render_to_string('core/perfis.html', {'unidades': []}, request=request)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
        self.assertIn("document.querySelector('#formCriarPerfil [name=\"csrfmiddlewaretoken\"]')?.value", html)
        middleware = CsrfViewMiddleware(lambda request: HttpResponse())
        for supplied_token, expected_allowed in [(None, False), (token, True), ('invalid', False)]:
            with self.subTest(token_valid=expected_allowed):
                headers = {'HTTP_X_CSRFTOKEN': supplied_token} if supplied_token else {}
                post = factory.post('/perfis/1/redefinir-senha/', **headers)
                post.COOKIES[settings.CSRF_COOKIE_NAME] = request.META['CSRF_COOKIE']
                middleware.process_request(post)
                result = middleware.process_view(post, lambda request: HttpResponse(), (), {})
                if expected_allowed:
                    self.assertIsNone(result)
                else:
                    self.assertEqual(result.status_code, 403)
