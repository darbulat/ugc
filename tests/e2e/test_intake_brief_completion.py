"""The actual paid form retains and submits the complete client brief."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import SIGNED
from tests.e2e.test_miniapp_selection_ui import SelectionNetwork, fill

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("native", [False, True])
def test_missing_fields_show_russian_errors_before_creation(
    page, platform, native
):
    network = SelectionNetwork()
    errors = open_app(
        page,
        network,
        platform,
        native=native,
        init_data=SIGNED,
        query="?view=order",
    )
    form = page.locator("#form-umc-intake")
    expect(form).to_be_visible()
    fill(page)
    hint = page.locator("#intake-required-error")

    def submit():
        if native:
            page.evaluate("window.__host.wa.MainButton.click()")
        else:
            page.locator("#btn-intake-create").click()

    for name, message in (
        ("policy", "Выберите условия заказа."),
        ("product", "Укажите ссылку на товар или сайт проекта."),
        ("brief", "Опишите задание для авторов."),
        ("count", "Укажите количество авторов."),
        ("honorarium", "Укажите гонорар одному автору."),
        ("due", "Укажите срок подбора авторов."),
        ("contact", "Укажите контакт для связи по заказу."),
    ):
        field = form.locator(f"#intake-{name}")
        value = field.input_value()
        set_value = field.select_option if name == "policy" else field.fill
        set_value("")
        submit()
        expect(hint).to_have_text(message)
        expect(field).to_be_focused()
        expect(field).to_have_attribute(
            "aria-errormessage", "intake-required-error"
        )
        assert not network.creates
        set_value(value)
        expect(hint).to_have_count(0)

    product = form.locator("#intake-product")
    url = product.input_value()
    product.fill("not a URL")
    submit()
    assert product.evaluate("(field) => field.validity.typeMismatch")
    expect(hint).to_have_count(0)
    assert not network.creates
    product.fill(url)
    submit()
    expect(page.locator("#intake-result")).to_be_visible()
    assert len(network.creates) == 1
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_full_brief_restores_and_submits_without_losing_filters(page, platform):
    network = SelectionNetwork()
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    expect(page.locator("#form-umc-intake")).to_contain_text(
        "Поля со звёздочкой обязательны"
    )
    for field in ("product", "brief", "due", "contact", "honorarium"):
        expect(page.locator(f"#intake-{field}")).to_have_attribute(
            "aria-describedby", f"intake-{field}-hint"
        )
        expect(page.locator(f"#intake-{field}-hint")).to_be_visible()
    page.locator("#btn-intake-create").click()
    assert not network.creates
    fill(page)
    for name, value in dict(
        city="Москва",
        content_usage="Вертикальное видео",
        brief_link="https://example.com/brief",
    ).items():
        page.locator("#intake-" + name).fill(value)
    page.locator("#intake-platform-youtube").check()
    page.locator("#intake-order-type").select_option("ugc_plus_placement")
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#intake-city")).to_have_value("Москва")
    expect(page.locator("#intake-platform-youtube")).to_be_checked()
    expect(page.locator("#intake-order-type")).to_have_value(
        "ugc_plus_placement"
    )
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    payload = network.creates[0]
    assert payload["targeting"]["city"] == "Москва"
    assert payload["targeting"]["platforms"] == ["youtube"]
    assert payload["targeting"]["brief_link"] == "https://example.com/brief"
    assert payload["order_type"] == "ugc_plus_placement"
    assert not errors
