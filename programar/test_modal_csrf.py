import re

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings


@override_settings(CSRF_COOKIE_HTTPONLY=True)
class ModalCSRFTest(SimpleTestCase):
    def test_modal_token_authorizes_json_post_with_httponly_cookie(self):
        factory = RequestFactory()
        request = factory.get('/programar/')
        request.user = AnonymousUser()
        html = render_to_string(
            'programar/partials/_modal_programacao.html', request=request,
        )
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
        cookie = request.META['CSRF_COOKIE']
        middleware = CsrfViewMiddleware(lambda request: HttpResponse())
        for path in ('/programar/api/salvar/', '/programar/api/excluir/'):
            with self.subTest(path=path):
                post = factory.post(path, '{}', content_type='application/json')
                post.COOKIES[settings.CSRF_COOKIE_NAME] = cookie
                middleware.process_request(post)
                self.assertEqual(
                    middleware.process_view(post, lambda request: HttpResponse(), (), {}).status_code,
                    403,
                )
                post = factory.post(
                    path, '{}', content_type='application/json', HTTP_X_CSRFTOKEN=token,
                )
                post.COOKIES[settings.CSRF_COOKIE_NAME] = cookie
                middleware.process_request(post)
                self.assertIsNone(middleware.process_view(post, lambda request: HttpResponse(), (), {}))
