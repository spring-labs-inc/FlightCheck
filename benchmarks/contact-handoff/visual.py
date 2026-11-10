"""Render the real Contact view with synthetic data and check it in headless Chromium."""
import hashlib
import json
import mimetypes
import os
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import django
from playwright.sync_api import sync_playwright

root = Path.cwd().resolve()
sys.path.insert(0, str(root))
from spring.test_env import apply_offline_test_env, assert_no_real_secrets

assert not (root / ".env").exists() and not (root / "spring-web/.env").exists()
apply_offline_test_env()
assert_no_real_secrets()
os.environ["DJANGO_SETTINGS_MODULE"] = "spring_web.settings"
from django.conf import settings

settings.DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
settings.ANALYTICS_COLLECTION_ACTIVE = False
django.setup()

from authn import views
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.staticfiles import finders
from django.test import RequestFactory
from django.urls import resolve

output = Path(sys.argv[1])
expected = sys.argv[2]
output.mkdir(parents=True, exist_ok=True)
factory = RequestFactory()
account = get_user_model()(username="benchmark", email="benchmark@example.invalid")
pages = {}
for identity, user, canonical in (("anonymous", AnonymousUser(), None),
                                  ("verified", account, account.email)):
    for mode in ("get", "invalid"):
        request = (factory.get("/contact/") if mode == "get" else
                   factory.post("/contact/", {"message": "Synthetic draft"}))
        request.resolver_match = resolve("/contact/")
        request.user = user
        request.session = {}
        with patch.object(views, "_verified_reply_to", return_value=canonical), \
             patch.object(views, "queue_transactional_email") as send:
            response = views.contact(request)
            assert response.status_code == 200
            send.assert_not_called()
        key = f"{identity}-{mode}"
        pages[key] = response.content
        (output / f"{key}.html").write_bytes(response.content)


def route_asset(route):
    url = urlsplit(route.request.url)
    if url.hostname != "preview.example.invalid":
        route.abort()
        return
    key = url.path.removeprefix("/contact/")
    if key in pages:
        route.fulfill(status=200, body=pages[key], content_type="text/html",
                      headers={"Content-Security-Policy": "form-action 'none'; connect-src 'none'"})
        return
    if url.path.startswith("/static/"):
        found = finders.find(url.path.removeprefix("/static/"))
        if found:
            path = Path(found).resolve()
            if path.is_relative_to(root):
                route.fulfill(path=path, content_type=mimetypes.guess_type(path)[0])
                return
    route.fulfill(status=404, body="")


records = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True, executable_path=os.environ["SPRINGDEV_CHROMIUM_BINARY"],
    )
    for width in (390, 1440):
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.route("**/*", route_asset)
        for key, html in pages.items():
            page.goto(f"https://preview.example.invalid/contact/{key}", wait_until="load")
            email = page.locator('input[name="email"]')
            alert = page.locator("#contact-errors")
            invalid = key.endswith("-invalid")
            assert email.count() == int(key.startswith("anonymous-")), key
            assert alert.count() == int(invalid), (key, width, "missing or unexpected alert")
            if invalid:
                assert alert.is_visible() and alert.inner_text() == expected, (key, width)
                assert alert.get_attribute("role") == "alert", (key, width)
                assert page.locator('textarea[name="message"]').input_value() == "Synthetic draft", key
                box = alert.bounding_box()
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, (key, width)
            records.append({"fixture": key, "width": width,
                            "html_sha256": hashlib.sha256(html).hexdigest()})
        page.close()
    browser.close()
(output / "browser.json").write_text(json.dumps(records, indent=2) + "\n")
print(f"PASS: {len(records)} Chromium Contact fixture/viewport checks")
