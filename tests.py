from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken


class RefreshRotationTests(TestCase):
	def setUp(self):
		User = get_user_model()
		self.user = User.objects.create_user(username='rotuser', email='rot@example.com', password='testpass')
		self.client = APIClient()

	def test_refresh_rotates_and_blacklists_old(self):
		# Issue initial refresh token
		initial = str(RefreshToken.for_user(self.user))

		# Call refresh endpoint to rotate
		res = self.client.post('/api/token/refresh/', {'refresh': initial}, format='json')
		self.assertEqual(res.status_code, 200)
		new_refresh = res.data.get('refresh')
		self.assertIsNotNone(new_refresh)
		self.assertNotEqual(initial, new_refresh)

		# Old token should be blacklisted
		out = OutstandingToken.objects.filter(token=initial).first()
		# outstanding token record may or may not exist depending on blacklist app behavior; check blacklisted flag
		if out:
			self.assertTrue(BlacklistedToken.objects.filter(token=out).exists())

		# Reuse old token should fail
		res2 = self.client.post('/api/token/refresh/', {'refresh': initial}, format='json')
		self.assertIn(res2.status_code, (400, 401))


