# core/tests/test_policy.py
import pytest
from django.contrib.auth.models import User
from core.models import UserProfile, Policy, No

@pytest.mark.django_db
def test_policy_created_with_user_profile():
    unidade = No.objects.create(nome='TI', tipo='setor')
    user = User.objects.create(username='john')
    profile = UserProfile.objects.create(user=user, unidade=unidade)

    assert hasattr(profile, 'policy')
    assert profile.policy.can_read is True
    assert profile.policy.can_write is False
    assert profile.policy.scope == 'RESTRICTED'