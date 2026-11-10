from pathlib import Path

root = Path.cwd()
template = root / "spring-web/templates/authn/contact_form.html"
tests = root / "spring-web/authn/tests/test_contact.py"
old = '    {{ form.non_field_errors }}'
alert = """    {% if form.errors %}
    <p id="contact-errors" role="alert" class="text-muted">Please correct the errors below.</p>
    {% endif %}
"""
text = template.read_text()
assert text.count(old) == 1
template.write_text(text.replace(old, alert + old))
with tests.open("a") as file:
    file.write('''

@override_settings(**PINNED)
class ContactErrorSummaryTests(TestCase):
    def test_unbound_form_does_not_show_error_summary(self):
        self.assertNotContains(self.client.get(reverse("contact")), 'id="contact-errors"')

    def test_invalid_anonymous_form_announces_errors_and_keeps_email_field(self):
        response = self.client.post(reverse("contact"), {"message": "Synthetic draft"})
        self.assertContains(response, 'id="contact-errors" role="alert"')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, "Synthetic draft")

    def test_invalid_verified_form_announces_errors_without_email_field(self):
        self.client.force_login(_user())
        response = self.client.post(reverse("contact"), {"message": "Synthetic draft"})
        self.assertContains(response, 'id="contact-errors" role="alert"')
        self.assertNotContains(response, 'name="email"')
        self.assertContains(response, "Synthetic draft")
''')
