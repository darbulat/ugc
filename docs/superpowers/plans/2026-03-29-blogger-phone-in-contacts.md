# Blogger Phone in Contacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show blogger's phone number to advertiser/manager/admin when blogger responds to an order, and display it in the mini app and admin panel.

**Architecture:** Add `blogger_phone` parameter to `_build_advertiser_contact_content()` and include it in the message text. Add `phone` field to miniapp Pydantic models. Add `phone` column to admin `BloggerProfileAdmin` view.

**Tech Stack:** Python, aiogram, FastAPI (miniapp), SQLAdmin

---

### Task 1: Add blogger phone to bot notification message

**Files:**
- Modify: `src/ugc_bot/bot/telegram/handlers/offer_responses.py:696-762` (`_build_advertiser_contact_content`)
- Modify: `src/ugc_bot/bot/telegram/handlers/offer_responses.py:827-978` (`_send_contact_immediately`)
- Test: `tests/unit/test_offer_response_contact_routing.py`

- [ ] **Step 1: Write failing test — phone appears in advertiser message**

In `tests/unit/test_offer_response_contact_routing.py`, add:

```python
@pytest.mark.asyncio
async def test_send_contact_includes_blogger_phone(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """Advertiser message includes blogger phone when available."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    advertiser = await create_test_user(
        user_repo,
        user_id=ADV_ID,
        external_id="801",
        username="advertiser",
        telegram="advertiser_tg",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=BLOGGER_ID,
        external_id="802",
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, BLOGGER_ID, confirmed=True, phone="+79001234567"
    )

    order = await create_test_order(
        InMemoryOrderRepository(),
        ADV_ID,
        order_id=ORDER_ID,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    await _send_contact_immediately(
        order=order,
        blogger_id=BLOGGER_ID,
        blogger_chat_id=blogger.telegram_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=None,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    sent_to_adv = [
        s for s in messenger_client.sent_text if s["chat_id"] == advertiser.telegram_id
    ]
    adv_msg = sent_to_adv[0]["text"] if sent_to_adv else ""
    assert "+79001234567" in adv_msg, "Advertiser should see blogger phone"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_offer_response_contact_routing.py::test_send_contact_includes_blogger_phone -v`
Expected: FAIL — phone not in message

- [ ] **Step 3: Check `create_test_blogger_profile` accepts `phone` kwarg**

Look at `tests/helpers/factories.py` — the `create_test_blogger_profile` function. If it does not accept `phone`, add it as an optional parameter that gets passed through to the `BloggerProfile` constructor. The `BloggerProfile` dataclass already has `phone: Optional[str] = None`.

- [ ] **Step 4: Add `blogger_phone` parameter to `_build_advertiser_contact_content`**

In `src/ugc_bot/bot/telegram/handlers/offer_responses.py`, modify the function signature at line 696:

```python
def _build_advertiser_contact_content(
    order: Order,
    creator_name: str,
    city: str,
    ugc_format: str,
    profile_url: str,
    has_telegram: bool,
    telegram_handle: str,
    texts: dict[str, str],
    creator_external_id: str | None = None,
    creator_max_id: str | None = None,
    blogger_phone: str | None = None,
) -> tuple[str, Keyboard | None]:
```

After the `contact_text` is built (after line 725), append the phone line:

```python
    if blogger_phone:
        contact_text += f"\n📞 Телефон: {blogger_phone}"
```

- [ ] **Step 5: Pass `blogger_phone` from `_send_contact_immediately`**

In `_send_contact_immediately`, the `profile` variable (line 848) is the `BloggerProfile`. Pass `blogger_phone=profile.phone` to both calls of `_build_advertiser_contact_content`:

At line 867 (advertiser call):
```python
    contact_text, open_profile_kb = _build_advertiser_contact_content(
        order,
        creator_name=creator_name,
        city=profile.city or "—",
        ugc_format=ugc_format,
        profile_url=profile.instagram_url,
        has_telegram=bool(user.telegram and user.telegram.strip()),
        telegram_handle=user.telegram or "",
        texts=t_adv,
        creator_external_id=user.telegram_id,
        creator_max_id=user.max_id,
        blogger_phone=profile.phone,
    )
```

At line 915 (manager call):
```python
    mgr_contact_text, mgr_kb = _build_advertiser_contact_content(
        order,
        creator_name=mgr_creator_name,
        city=profile.city or "—",
        ugc_format=mgr_ugc_format,
        profile_url=profile.instagram_url,
        has_telegram=bool(user.telegram and user.telegram.strip()),
        telegram_handle=user.telegram or "",
        texts=t_mgr,
        creator_external_id=user.telegram_id,
        creator_max_id=user.max_id,
        blogger_phone=profile.phone,
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_offer_response_contact_routing.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/bot/telegram/handlers/offer_responses.py tests/unit/test_offer_response_contact_routing.py tests/helpers/factories.py
git commit -m "feat: include blogger phone in offer response notifications"
```

---

### Task 2: Add phone to miniapp CreatorItem and CreatorDetailResponse

**Files:**
- Modify: `src/ugc_bot/miniapp/api.py:282-314` (Pydantic models)
- Modify: `src/ugc_bot/miniapp/api.py:1768-1841` (endpoints)
- Test: `tests/unit/test_miniapp_manager_endpoints.py`

- [ ] **Step 1: Write failing test — phone in creators list**

In `tests/unit/test_miniapp_manager_endpoints.py`, update `TestManagerCreatorsEndpoint.test_returns_creators_for_manager`:

After line 185 (`profile.instagram_url = ...`), add:
```python
        profile.phone = "+79001234567"
```

After line 218 (`assert result.creators[0].desired_price is None`), add:
```python
        assert result.creators[0].phone == "+79001234567"
```

- [ ] **Step 2: Write failing test — phone in creator detail**

In `TestManagerCreatorDetailEndpoint.test_returns_creator_detail`, after line 400 (`profile.instagram_url = ...`), add:
```python
        profile.phone = "+79009876543"
```

After line 418 (`assert result.ugc_video_url == ...`), add:
```python
        assert result.phone == "+79009876543"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_miniapp_manager_endpoints.py::TestManagerCreatorsEndpoint::test_returns_creators_for_manager tests/unit/test_miniapp_manager_endpoints.py::TestManagerCreatorDetailEndpoint::test_returns_creator_detail -v`
Expected: FAIL — `phone` attribute not found on response models

- [ ] **Step 4: Add `phone` field to Pydantic models**

In `src/ugc_bot/miniapp/api.py`:

`CreatorItem` (line 282):
```python
class CreatorItem(BaseModel):
    """Creator summary for manager view."""

    blogger_id: str
    instagram_url: str | None = None
    telegram: str | None = None
    name: str | None = None
    desired_price: float | None = None
    phone: str | None = None
```

`CreatorDetailResponse` (line 306):
```python
class CreatorDetailResponse(BaseModel):
    """Creator profile and current UGC video URL."""

    blogger_id: str
    instagram_url: str | None = None
    telegram: str | None = None
    ugc_video_url: str | None = None
    in_offer: bool = True
    phone: str | None = None
```

- [ ] **Step 5: Populate `phone` in `manager_creators` endpoint**

At line 1781 in the `CreatorItem(...)` constructor, add `phone`:
```python
        all_creators.append(
            CreatorItem(
                blogger_id=str(bid),
                instagram_url=(profile.instagram_url if profile else None),
                telegram=tg,
                name=name,
                desired_price=price,
                phone=profile.phone if profile else None,
            )
        )
```

- [ ] **Step 6: Populate `phone` in `manager_creator_detail` endpoint**

At line 1835 in the `CreatorDetailResponse(...)` constructor, add `phone`:
```python
    return CreatorDetailResponse(
        blogger_id=str(blogger_id),
        instagram_url=profile.instagram_url if profile else None,
        telegram=user.telegram if user else None,
        ugc_video_url=dispatch.ugc_video_url,
        in_offer=dispatch.in_offer,
        phone=profile.phone if profile else None,
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_miniapp_manager_endpoints.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/ugc_bot/miniapp/api.py tests/unit/test_miniapp_manager_endpoints.py
git commit -m "feat: add blogger phone to miniapp creator endpoints"
```

---

### Task 3: Add phone to admin BloggerProfileAdmin view

**Files:**
- Modify: `src/ugc_bot/admin/app.py:1421-1460` (`BloggerProfileAdmin`)

- [ ] **Step 1: Add `phone` to `column_list` and `column_labels`**

In `src/ugc_bot/admin/app.py`, `BloggerProfileAdmin` class:

Add `BloggerProfileModel.phone` to `column_list` after `BloggerProfileModel.city`:
```python
    column_list = [
        BloggerProfileModel.user_id,
        BloggerProfileModel.instagram_url,
        BloggerProfileModel.confirmed,
        BloggerProfileModel.city,
        BloggerProfileModel.phone,
        BloggerProfileModel.country,
        BloggerProfileModel.blogger_gender,
        BloggerProfileModel.audience_gender,
        BloggerProfileModel.audience_age_min,
        BloggerProfileModel.audience_age_max,
        BloggerProfileModel.audience_geo,
        BloggerProfileModel.price,
        BloggerProfileModel.barter,
        BloggerProfileModel.work_format,
        BloggerProfileModel.updated_at,
    ]
```

Add label to `column_labels`:
```python
        BloggerProfileModel.phone: "Телефон",
```

- [ ] **Step 2: Run `make all` to verify nothing breaks**

Run: `make all`
Expected: format-check + lint + typecheck + coverage all pass

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/admin/app.py
git commit -m "feat: show blogger phone in admin profile view"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run full test suite**

Run: `make all`
Expected: ALL PASS, coverage ≥ 98%

- [ ] **Step 2: Verify no regressions in existing contact routing tests**

Run: `uv run pytest tests/unit/test_offer_response_contact_routing.py tests/unit/test_miniapp_manager_endpoints.py -v`
Expected: ALL PASS
