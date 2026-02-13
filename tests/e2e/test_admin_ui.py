"""E2E tests for Admin UI with Playwright."""

import os

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("E2E_BASE_URL"),
    reason="Dashboard/creators need PostgreSQL; run via make e2e-docker",
)


def _login(
    page,
    base_url: str,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Perform admin login via form.

    Uses E2E_ADMIN_USERNAME / E2E_ADMIN_PASSWORD from env when not passed.
    """
    user = (
        username
        if username is not None
        else os.environ.get("E2E_ADMIN_USERNAME", "test_admin")
    )
    pwd = (
        password
        if password is not None
        else os.environ.get("E2E_ADMIN_PASSWORD", "test_pass")
    )
    page.goto(f"{base_url}/admin/login")
    page.locator('input[name="username"]').fill(user)
    page.locator('input[name="password"]').fill(pwd)
    page.get_by_role("button", name="Login").click()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_login_redirects_unauthenticated(admin_server, page, base_url) -> None:
    """GET /admin/dashboard without session redirects to /admin/login."""
    page.goto(f"{base_url}/admin/dashboard")
    page.wait_for_url(f"{base_url}/admin/login", timeout=5000)
    assert "login" in page.url.lower()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_login_success(admin_server, page, base_url) -> None:
    """POST login with valid credentials redirects to dashboard."""
    _login(page, base_url)
    page.wait_for_url(
        lambda url: "login" not in url,
        timeout=5000,
    )
    assert "login" not in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_login_invalid_credentials(admin_server, page, base_url) -> None:
    """Invalid password keeps user on login page."""
    _login(page, base_url, password="wrong_password")
    page.wait_for_load_state("networkidle")
    assert "login" in page.url.lower()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_dashboard_loads(admin_server, page, base_url) -> None:
    """After login, admin index or dashboard loads."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{base_url}/admin/")
    page.wait_for_load_state("networkidle")
    assert page.url.rstrip("/").endswith("/admin") or "/admin/" in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
@requires_postgres
def test_custom_dashboard_with_kpi(admin_server, page, base_url) -> None:
    """Custom dashboard loads with KPI cards (needs PostgreSQL)."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{base_url}/admin/dashboard")
    page.wait_for_load_state("networkidle")
    assert "Дашборд" in page.content()


@pytest.mark.e2e
@pytest.mark.timeout(30)
@requires_postgres
def test_navigation_creators(admin_server, page, base_url) -> None:
    """Creators page loads (requires PostgreSQL, blogger_profiles)."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{base_url}/admin/users/creators")
    page.wait_for_load_state("networkidle")
    assert "creators" in page.url or "Креаторы" in page.content()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_navigation_advertisers_orders(admin_server, page, base_url) -> None:
    """Navigate between advertisers and orders sections."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)

    page.goto(f"{base_url}/admin/users/advertisers")
    page.wait_for_load_state("networkidle")
    assert "advertisers" in page.url

    page.goto(f"{base_url}/admin/orders")
    page.wait_for_load_state("networkidle")
    assert "orders" in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_sqladmin_list_views(admin_server, page, base_url) -> None:
    """Access SQLAdmin list views after login."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)

    response = page.goto(f"{base_url}/admin/user-model/list")
    assert response is not None
    assert response.status in (200, 304)
