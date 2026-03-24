"""EN locale texts."""

EN: dict[str, str] = {
    "start_message": (
        "UMC — UGC service.\n"
        "For business — creator matching; for creators — orders."
    ),
    "support_response": (
        "Support: @usemycontent\nContact us for any questions!"
    ),
    "receipt_description": "Use My Content platform services",
    "btn_creator": "I'm a creator",
    "btn_advertiser": "I need UGC creators",
    "btn_support": "💬 Support",
    "btn_my_orders": "📂 My orders",
    "btn_change_role": "Change role",
    "btn_create_profile": "Create profile",
    "btn_advertiser_start": "Start",
    "btn_create_order": "➕ Create order",
    "btn_confirm_instagram": "✅ Confirm Instagram",
    "btn_confirm_agreement": "✅ Confirm agreement",
    "btn_edit_profile": "Edit profile",
    "btn_my_profile": "👤 My profile",
    "btn_work_format_ads": "📢 Place ads in my account",
    "btn_work_format_ugc_only": "❌ UGC only (no placement)",
    "btn_phone_request": "📱 Share phone number",
    "btn_location_request": "📍 Share location",
    "btn_location_map": "🗺 Pick on map",
    "btn_city_picker": "Choose city",
    "btn_edit_profile_blogger": "Edit blogger profile",
    "btn_edit_profile_advertiser": "Edit advertiser profile",
    "btn_audience_f": "👩 Mostly women",
    "btn_audience_m": "👨 Mostly men",
    "btn_audience_a": "👥 Mixed",
    "btn_gender_m": "Male",
    "btn_gender_f": "Female",
    "btn_age_0_17": "under 18",
    "btn_age_18_24": "18–24",
    "btn_age_25_34": "25–34",
    "btn_age_35_44": "35–44",
    "btn_age_45_99": "45+",
    "btn_barter_yes": "Yes",
    "btn_barter_no": "No",
    "btn_payout": "Payout",
    "btn_back": "Back",
    "btn_forward": "Forward",
    "btn_back_arrow": "⬅️ Back",
    "btn_forward_arrow": "Forward ➡️",
    "btn_pay_order": "💳 Pay #{creation_number}",
    "btn_open_profile": "🔗 Open profile",
    "btn_write_telegram": "Message in Telegram",
    "btn_ok_skipped": "OK, skipped.",
    "order_type_ugc_only": "🎥 UGC video for brand",
    "order_type_ugc_placement": "📢 UGC + placement",
    "order_photo_add": "📷 Add photo",
    "order_photo_skip": "⏭ Skip",
    "coop_barter": "🎁 Barter",
    "coop_payment": "💰 Payment",
    "coop_both": "🔄 Barter + payment",
    "content_social": "📱 Brand socials",
    "content_ads": "📢 Ads (targeting, banners)",
    "content_both": "🔄 Socials and ads",
    "deadlines_3": "⏱ Up to 3 days",
    "deadlines_7": "⏱ Up to 7 days",
    "deadlines_14": "⏱ Up to 14 days",
    "msg_user_not_found": "User not found.",
    "msg_user_not_found_start": "User not found. Start with /start.",
    "msg_registration_blocked": "Blocked users cannot register.",
    "msg_registration_pause": "Paused users cannot register.",
    "msg_instagram_blocked": "Blocked users cannot verify account.",
    "msg_instagram_pause": "Paused users cannot verify account.",
    "msg_complaint_blocked": "Blocked users cannot file complaints.",
    "msg_complaint_pause": "Paused users cannot file complaints.",
    "msg_order_creation_blocked": "Blocked users cannot create orders.",
    "msg_order_creation_pause": "Paused users cannot create orders.",
    "msg_payment_blocked": "Blocked users cannot pay for orders.",
    "msg_payment_pause": "Paused users cannot pay for orders.",
    "msg_feedback_blocked": "Blocked users cannot leave feedback.",
    "msg_feedback_pause": "Paused users cannot leave feedback.",
    "msg_feedback_rate_blocked": "Blocked users cannot rate.",
    "msg_feedback_rate_pause": "Paused users cannot rate.",
    # Feedback flow messages
    "msg_fb_thanks_saved": "Thanks, response saved.",
    "msg_fb_thanks_feedback": "Thanks for your feedback.",
    "msg_fb_interaction_not_found": "Interaction not found.",
    "msg_fb_insufficient_rights": "Insufficient rights.",
    "msg_fb_no_deal_question_blog": "What was the reason you couldn't reach an agreement?",
    "msg_fb_no_deal_question_adv": "What was the reason you couldn't reach an agreement?",
    "msg_fb_thanks_short": "Thanks.",
    "msg_fb_issue_prompt": (
        "Describe the issue and attach screenshots of the conversation or "
        "other evidence. This will help us look into it.\n"
        "👉 Write your message, attach photos and tap «Send»."
    ),
    "msg_fb_postpone_max": (
        "Maximum postponements reached. Status set to 'No deal'."
    ),
    "msg_fb_postpone_72": "Check postponed by 72 h. Postponements: {cnt}/{max_cnt}",
    "msg_fb_postpone_ok_blog": (
        "Okay, we'll get back to this later 👍 "
        "If the advertiser messages you — just reply."
    ),
    "msg_fb_postpone_ok_adv": (
        "Got it, we'll get back to this later 👍\n"
        "ℹ️ Creator doesn't see your contacts. "
        "You need to initiate contact."
    ),
    "msg_fb_ok_blog": (
        "Thanks for your feedback 👍 If you need help — we're here."
    ),
    "msg_fb_ok_adv": (
        "Thanks for your feedback 👍 "
        "Wishing you a smooth collaboration with the creator."
    ),
    "msg_fb_invalid_format": "Invalid format.",
    "msg_fb_invalid_response": "Invalid response format.",
    "msg_fb_invalid_status": "Invalid status.",
    "msg_fb_invalid_id": "Invalid identifier.",
    "msg_fb_error_try_later": "An error occurred. Please try later.",
    "msg_fb_no_deal_other_prompt": "Please write the reason:",
    "msg_fb_enter_reason_text": "Please enter the reason as text.",
    "msg_fb_session_expired": "Session expired. Please answer the feedback question again.",
    "msg_fb_session_expired_nps": "Session expired. Please answer the rating question again.",
    "msg_fb_error_try_again": "Error. Please try again.",
    "msg_fb_add_description_photo": "Add a description or photo, then tap «Send».",
    "msg_fb_add_description_before_send": "Add a description or photo before sending.",
    "msg_fb_complaint_error": (
        "An error occurred while creating the request. Please try again "
        "or contact support via the menu."
    ),
    "msg_fb_complaint_accepted": (
        "We have received your request. Support will look into it. "
        "If needed, tap «Support» in the menu."
    ),
    "msg_fb_nps_done_btn": "Done",
    "msg_fb_nps_thank": (
        "Thank you! 🙌\n"
        "Your feedback has been saved and helps us make UMC better 🙏"
    ),
    "msg_fb_nps_question": "Please rate your experience with UMC from 1 to 5 ⭐",
    "msg_fb_nps_prompt_5_adv": (
        "Thanks for the 5 ⭐ — we're glad the platform worked well for you! 🙌\n"
        "If you have 1–2 ideas to make the service even better (interface, "
        "creator matching, notifications, etc.) — reply with them.\n"
        "We read every suggestion to improve the platform."
    ),
    "msg_fb_nps_prompt_5_blog": (
        "Thanks for the 5 ⭐ — we're glad working with advertisers via UMC "
        "is comfortable for you! 🙌\n"
        "If you have 1–2 ideas to improve the service (dashboard, "
        "order matching, terms, support) — reply with them.\n"
        "We read every suggestion to improve the platform."
    ),
    "msg_fb_nps_prompt_34_adv": (
        "Thanks for your rating 🙏\n"
        "We want to understand what we can improve in your experience with UMC.\n"
        "Please write in one message:\n"
        "– what didn't work (matching, speed, interface, communication)."
    ),
    "msg_fb_nps_prompt_34_blog": (
        "Thanks for your rating 🙏\n"
        "We want to understand what we can improve in your experience with orders.\n"
        "Please write in one message:\n"
        "– what was difficult or inconvenient (terms, communication with advertiser, "
        "interface, notifications, etc.)."
    ),
    "msg_fb_nps_prompt_1_adv": (
        "Thanks for the honest 1 ⭐ — we really want to know 🙏\n"
        "We're sorry your experience with UMC was negative.\n"
        "Please describe in one message what went wrong:\n"
        "– issues with the creator;\n"
        "– platform difficulties;\n"
        "– errors, delays, misunderstandings, etc.\n"
        "We will look into the situation."
    ),
    "msg_fb_nps_prompt_1_blog": (
        "Thanks for the honest 1 ⭐ — we really want to know 🙏\n"
        "We're sorry your experience with UMC was negative.\n"
        "Please describe in one message what happened:\n"
        "– issues with the advertiser;\n"
        "– terms difficulties;\n"
        "– platform technical issues;\n"
        "– any other points.\n"
        "We will look into the situation."
    ),
    "msg_fb_issue_send_btn": "📤 Send",
    "msg_fb_feedback_ok": "✅ All went well",
    "msg_fb_feedback_no_deal": "❌ No deal",
    "msg_fb_feedback_postpone": "⏳ Haven't contacted yet",
    "msg_fb_feedback_issue": "⚠️ Problem / suspected fraud",
    "msg_fb_no_deal_conditions": "💰 Didn't agree on terms",
    "msg_fb_no_deal_timing": "⏱ Timing didn't work",
    "msg_fb_no_deal_differed": "📝 Terms differed from offer",
    "msg_fb_no_deal_creator_change": "📝 Creator wanted to change terms",
    "msg_fb_no_deal_other": "🤝 Other",
    "msg_fb_score_1_to_5": "Rating must be from 1 to 5.",
    "msg_fb_thanks_for_rating": "Thanks for your rating!",
    "msg_fb_no_description": "No description",
    # Feedback scheduler: request messages (placeholders: creator_link, order_link_part)
    "msg_feedback_request_adv": (
        "We want to make sure everything went well 🙌\n"
        "Were you able to get in touch with the creator{creator_link}?\n"
        "Choose the option that fits:"
    ),
    "msg_feedback_request_blog": (
        "We want to make sure everything went well 🙌\n"
        "Were you able to get in touch with the advertiser {order_link_part}"
    ),
    "msg_choose_role": "Choose role via /role.",
    "msg_fill_profile_orders": (
        "Fill your profile (/advertiser or /creator) to see orders."
    ),
    "msg_confirm_agreement": "Please confirm agreement with platform documents.",
    "msg_agreements_intro_default": (
        "Profile created. Please read the documents and confirm."
    ),
    "msg_label_offer": "📄 Offer",
    "msg_label_privacy": "🔒 Privacy Policy",
    "msg_label_consent": "🧾 Consent to personal data processing",
    "msg_confirm_docs_fallback": (
        "Please confirm your agreement with the platform documents."
    ),
    "msg_no_orders": "You have no orders yet. /create_order",
    "msg_no_blogger_orders": "You haven't responded yet. Offers come to the bot.",
    "msg_blogger_profile_empty": "Blogger profile not filled.",
    "msg_advertiser_profile_empty": "Advertiser profile not filled.",
    "msg_advertiser_profile_fill": "Advertiser profile not filled. Command: /advertiser",
    "msg_creator_profile_fill": "Profile not filled. Command: /creator",
    "msg_confirm_instagram_first": "Confirm Instagram before responding.",
    "msg_confirm_agreement_first": "Confirm agreement first.",
    "msg_invalid_order_amount": "Invalid order amount.",
    "msg_order_amount_too_large": "Order amount too large for Telegram invoice.",
    "msg_invoice_failed": "Failed to create invoice. Try again later.",
    "msg_pay_order_usage": "Usage: /pay_order <order_id>",
    "msg_invalid_order_id": "Invalid order_id format.",
    "msg_invalid_order_format": "Invalid order format.",
    "msg_order_not_found": "Order not found.",
    "msg_order_not_yours": "Order does not belong to advertiser.",
    "msg_order_not_new": "Order is not in NEW status.",
    "msg_pricing_not_configured": "Pricing not configured. Contact support.",
    "msg_payment_provider_not_configured": "Payment provider not configured.",
    "msg_order_undetermined": "Could not determine order.",
    "msg_title_payment": "Order payment",
    "btn_pay_invoice": "Pay {amount}",
    "msg_referral_payout_today": "You already requested payout today.",
    "msg_referral_payout_unavailable": "Payout unavailable: no balance or request pending.",
    "msg_referral_payout_sent": "Payout request sent to support.",
    "msg_referral_payout_notify_failed": (
        "Request created but could not notify support. Contact support manually."
    ),
    "msg_referral_payout_blocked": "You cannot request payout.",
    "msg_referral_payout_pause": "Paused users cannot request payout.",
    "msg_referral_no_users": "You have no referred users yet.",
    "msg_referral_access_denied": "Access denied.",
    "msg_referral_blocked": "Blocked users cannot use this command.",
    "msg_referral_pause": "Paused users cannot use this command.",
    "msg_referral_list_blocked": "Blocked users cannot view the list.",
    "msg_referral_list_pause": "Paused users cannot view the list.",
    "msg_referral_list_title": "Your referrals (page {page}/{total_pages}):",
    "msg_referral_list_empty": "Your referrals: none yet.",
    "msg_referral_pending_block": "Haven't filled creator profile (remind them):",
    "msg_referral_no_pending": "No referrals without profile.",
    "msg_referral_link_intro": "Your referral link:",
    "lbl_referral_stats": "📊 Referral stats",
    "lbl_referral_creators": "Creators referred",
    "lbl_referral_orders": "Orders completed",
    "lbl_referral_income_month": "Income this month",
    "lbl_referral_income_total": "Total earned",
    "lbl_referral_paid": "Paid out",
    "lbl_referral_balance": "Current balance",
    "lbl_referral_orders_done": "orders completed",
    "lbl_referral_income_line": "• {amount} {symbol} ({count} orders)",
    "lbl_referral_approx_total": "≈ {amount} {symbol} (approximate total)",
    "lbl_referral_paid_currency": "Paid: {amount} {symbol}",
    "lbl_referral_pending_currency": "Pending: {amount} {symbol}",
    "btn_referral_payout_currency": "Withdraw {amount} {symbol}",
    "msg_referral_payout_today_currency": "You already requested {currency} payout today.",
    "msg_offer_new_response": (
        "New response to your order 🙌\n\n"
        "👤 Creator: {creator}\n"
        "📍 City: {city}\n"
        "🎬 Format: {format}\n"
        "💼 Ready to work on offer terms\n"
        "🔗 Creator profile:\n{profile_url}"
    ),
    "lbl_creator_fallback": "Creator",
    "lbl_phone_dash": "Phone: —",
    "lbl_telegram_dash": "Telegram: —",
    "msg_offer_contacts_header": "📞 Advertiser contacts:\n\n",
    "msg_advertiser_new_response_what_next": (
        "🔔 What's next\n\n"
        "💬 Message the creator and discuss details\n"
        "✅ Creator has read the offer and is ready to work on these terms\n"
        "⏱ We recommend getting in touch within 30 min\n\n"
        "⚠️ Reminder\n\n"
        "🧷 Do not change offer terms\n"
        "🔄 If terms change, the creator may decline\n"
        "➡️ You always initiate contact"
    ),
    "msg_offer_response_blocked": "Blocked users cannot respond to offers.",
    "msg_offer_response_pause": "Paused users cannot respond to offers.",
    "msg_advertiser_contacts_warning": (
        "⚠️ **Safe workflow with creators:**\n\n"
        "• Platform does not recommend prepayment\n"
        "• Pay after receiving watermarked preview\n"
        "• Verify content quality before final payment\n"
        "• Negotiations and payments are between you and the creator"
    ),
    "msg_my_orders_blocked": "Blocked users cannot view orders.",
    "msg_my_orders_pause": "Paused users cannot view orders.",
    "msg_orders_title": "Your orders (page {page}/{total_pages}):",
    "msg_orders_blogger_title": "Orders you responded to (page {page}/{total_pages}):",
    "msg_order_status": "Status: {status_label}",
    "msg_order_creators": "Creators: {bloggers_needed}",
    "msg_order_matched": "Matched: {matched_count} / {bloggers_needed}",
    "msg_order_date_created": "Created: {date}",
    "msg_order_date_completed": "Completed: {date}",
    "msg_order_link": "Project link: {link}",
    "msg_order_format": "Format: {order_type}",
    "msg_order_type_ugc": "UGC video for brand",
    "msg_order_type_placement": "UGC + placement",
    "msg_order_price": "Price per UGC: {price}",
    "msg_order_barter": "Barter: {desc}",
    "msg_status_new": "Created",
    "msg_status_pending_moderation": "Pending moderation",
    "msg_status_active": "Active",
    "msg_status_closed": "Closed",
    "msg_choose_city": "Choose city from list.",
    "msg_choose_city_or_type": "Enter nearest city or tap «Choose city»",
    "msg_city_multiple_regions": "City in multiple regions. Choose region:",
    "msg_session_expired": "Session expired. Start over.",
    "msg_session_expired_orders": "Session expired. Start over with «Create order».",
    "msg_session_expired_profile": "Session expired. Open «My profile» again.",
    "msg_profile_not_found": "Profile not found.",
    "msg_profile_not_found_role": "Profile not found. Choose role via /role.",
    "msg_profile_incomplete": "Profile incomplete.",
    "msg_choose_profile_edit": "Choose profile to edit:",
    "msg_choose_section_edit": "Choose section to edit:",
    "msg_choose_section_keyboard": "Choose one of the sections on the keyboard.",
    "msg_profile_updated": "Profile updated.",
    "msg_advertiser_profile_not_found": "Advertiser profile not found.",
    "msg_unknown_field": "Unknown field.",
    "msg_profile_update_failed": "Failed to update profile.",
    "err_city_not_place_use_map": (
        "Could not update profile. Please indicate your location on the "
        "map or share your geolocation."
    ),
    "err_instagram_format_example": "Invalid link format. Example: instagram.com/name",
    "err_instagram_invalid": "Invalid Instagram link format.",
    "err_instagram_taken": "This Instagram is already registered. Use another one.",
    "msg_city_picker_edit": (
        "Enter nearest city or tap «Choose city» and select from list."
    ),
    "msg_choose_buttons": "Choose one of the options.",
    "msg_name_updated": "Name updated.",
    # Profile display
    "lbl_profile_your": "👤 Your profile",
    "lbl_profile_general": "📋 General",
    "lbl_profile_name": "Name",
    "lbl_profile_roles": "Roles",
    "lbl_profile_status": "Status",
    "lbl_profile_blogger": "📸 Creator profile",
    "lbl_profile_not_filled": "Not filled",
    "lbl_profile_advertiser": "🏢 Advertiser profile",
    "lbl_status_new": "New",
    "lbl_status_active": "Active",
    "lbl_status_pause": "Paused",
    "lbl_status_blocked": "Blocked",
    "lbl_audience_male": "Male",
    "lbl_audience_female": "Female",
    "lbl_audience_all": "All",
    "lbl_blogger_gender_male": "Male",
    "lbl_blogger_gender_female": "Female",
    "lbl_role_blogger": "Creator",
    "lbl_role_advertiser": "Advertiser",
    "lbl_yes": "Yes",
    "lbl_no": "No",
    "lbl_work_format_ads": "Place ads in your account",
    "lbl_work_format_ugc": "UGC only",
    "lbl_instagram": "Instagram",
    "lbl_confirmed": "Verified",
    "lbl_city": "City",
    "lbl_country": "Country",
    "lbl_region": "Region",
    "lbl_gender": "Gender",
    "lbl_birth_date": "Birth date",
    "lbl_topics": "Topics",
    "lbl_audience": "Target audience",
    "lbl_geo": "Geography",
    "lbl_price": "Price",
    "lbl_barter": "Barter",
    "lbl_work_format": "Work format",
    "lbl_phone": "Phone",
    "lbl_brand": "Brand",
    "lbl_activity": "Activity",
    "lbl_site": "Site",
    "lbl_years": "years",
    "prompt_edit_nickname": "Enter new name:",
    "prompt_edit_instagram_url": "Attach link instagram.com/name:",
    "prompt_edit_city": "What city are you from?",
    "prompt_edit_blogger_gender": "Your gender:",
    "prompt_edit_birth_date": "Birth date as DD.MM.YYYY (e.g. 15.05.1995):",
    "prompt_edit_topics": "List 1–3 topics, comma-separated:",
    "prompt_edit_audience_gender": "Who mainly watches your content?",
    "prompt_edit_audience_age": "Main age of your audience?",
    "prompt_edit_audience_geo": "Up to 3 cities, comma-separated:",
    "prompt_edit_price": "Price for 1 UGC video ({currency}):",
    "prompt_edit_barter": "Ready to work on barter?",
    "prompt_edit_work_format": "How do you work with brands?",
    "prompt_edit_name": "Enter name:",
    "prompt_edit_phone": "Phone number for contact. Example: +1234567890",
    "prompt_edit_brand": "Your brand / company name:",
    "prompt_edit_site_link": "Link to site, product or brand socials:",
    "prompt_edit_generic": "Enter new value:",
    "lbl_edit_nickname": "Name",
    "lbl_edit_instagram": "Instagram",
    "lbl_edit_city": "City",
    "lbl_edit_blogger_gender": "Gender",
    "lbl_edit_birth_date": "Birth date",
    "lbl_edit_topics": "Topics",
    "lbl_edit_audience_gender": "Audience gender",
    "lbl_edit_audience_age": "Audience age",
    "lbl_edit_audience_geo": "Audience geography",
    "lbl_edit_price": "Price",
    "lbl_edit_barter": "Barter",
    "lbl_edit_work_format": "Work format",
    "lbl_edit_name": "Name",
    "lbl_edit_phone": "Phone",
    "lbl_edit_brand": "Brand",
    "lbl_edit_company_activity": "Company activity",
    "lbl_edit_site_link": "Site link",
    "msg_whats_your_name": "What's your name?",
    "msg_choose_action": "Choose action:",
    "msg_what_city": "What city are you from?\nE.g. London / New York",
    "msg_brand_name": "Your brand / company name:",
    "msg_company_activity": "What does your company do?",
    "msg_brand_link": "Link to site, product or brand socials:",
    "msg_after_registration": "You can now create an order and find UGC creators.",
    "msg_advertiser_intro": (
        "You chose the advertiser role.\n"
        "Let's create your profile so you can place orders."
    ),
    "msg_creator_intro": (
        "You're a UGC creator. Brands look for creators here — a complete "
        "profile helps you get matched and receive relevant orders.\n\n"
        "Fill in your profile in a few minutes and you're in."
    ),
    "msg_step_ask_name": "What's your name?\n\nStep 1 of 12",
    "msg_step_ask_instagram": "Send link in format instagram.com/name\n\nStep 2 of 12",
    "msg_step_ask_instagram_first": "Send link in format instagram.com/name\n\nStep 1 of 12",
    "msg_step_ask_city": (
        "Brands match creators by city for product delivery and offline work. "
        "What city are you from?\n\nStep 3 of 12"
    ),
    "msg_step_ask_birth_date": (
        "Enter birth date as DD.MM.YYYY (e.g. 15.05.1995):\n\nStep 4 of 12"
    ),
    "msg_step_ask_gender": "Your gender:\n\nStep 5 of 12",
    "msg_step_ask_topics": (
        "What's your content about?\n"
        "List 1–5 topics, comma-separated: business, fitness, beauty, "
        "travel, food, fashion, family, tech, lifestyle, etc.\n\nStep 6 of 12"
    ),
    "msg_step_ask_audience_gender": (
        "Who mainly watches your content? By observation or stats\n\nStep 7 of 12"
    ),
    "msg_step_ask_audience_age": "Main age of your audience?\n\nStep 8 of 12",
    "msg_step_ask_audience_geo": (
        "Which cities is your audience in? Up to 3 cities, comma-separated\n\nStep 9 of 12"
    ),
    "msg_step_ask_price": (
        "Brands filter by budget — your price speeds up deals. "
        "Price for one UGC video ({currency})? E.g. 500, 1000, 2000\n\nStep 10 of 12"
    ),
    "msg_step_ask_barter": (
        "Many orders are barter — «Yes» increases offers. "
        "Ready to work with brands on barter sometimes?\n\nStep 11 of 12"
    ),
    "msg_step_ask_work_format": (
        "Besides UGC, how else can you work with brands? "
        "Last step before matching.\n\nStep 12 of 12"
    ),
    "msg_agreements_intro_creator": (
        "Almost done. Please read the documents and confirm agreement."
    ),
    "msg_profile_created": (
        "Profile created 👍\n\n"
        "Brands are looking for creators — a complete profile increases "
        "your chances to get offers.\n\n"
        "Last step: verify your Instagram. This helps:\n"
        "— protect brands from fakes\n"
        "— build trust in your profile\n"
        "— get orders faster"
    ),
    "msg_instagram_already_registered": (
        "This Instagram account is already registered. "
        "Use another account or contact support."
    ),
    "msg_work_format_choose": (
        "Choose one: Place ads in my account or UGC only (no placement)."
    ),
    "msg_registration_aborted": (
        "Registration aborted. To finish, open «My profile» and confirm agreement."
    ),
    "err_instagram_empty": "Link cannot be empty. Send link as instagram.com/name",
    "err_instagram_format": "Invalid format. Need a link like instagram.com/name",
    "err_instagram_example": "Invalid Instagram link. Example: https://instagram.com/name",
    "err_gender_choose": "Choose one: Male or Female.",
    "err_audience_choose": "Choose: Mostly women, men or Mixed.",
    "err_age_choose": "Choose one of the age options.",
    "err_barter_choose": "Choose Yes or No.",
    "err_price_number": "Enter a number, e.g. 500, 1000, 2000.",
    "err_geo_max_cities": "Enter no more than 3 cities, comma-separated.",
    # Validators (shared)
    "err_not_bot_command": (
        "Do not use bot commands as your answer. Enter text again."
    ),
    "err_offer_text_min": "Describe the task in more detail (min {min} characters).",
    "err_offer_text_max": "Text too long (max {max} characters).",
    "err_barter_required": "Describe the barter offer.",
    "err_barter_min": "Describe the barter (min {min} characters).",
    "err_barter_max": "Text too long (max {max} characters).",
    "err_url_max": "Link too long (max {max} characters).",
    "err_url_scheme": "Enter a link (http:// or https://).",
    "err_url_invalid": "Enter a valid link.",
    "err_url_example": ("Enter a valid link (e.g. example.com or site.com)."),
    "err_product_link_empty": "Link cannot be empty. Enter again:",
    "err_geo_required": (
        "Specify one option: city, region or country. "
        "Examples: London, UK, Worldwide"
    ),
    "err_geo_max": "Text too long (max {max} characters).",
    "err_min_chars": "Enter at least {min} characters.",
    "err_max_chars": "Max {max} characters.",
    "err_phone_empty": "Phone number cannot be empty. Enter again:",
    "err_phone_digits": "Enter a valid number (10–11 digits). Example: 89001110777",
    "err_phone_too_many": "Too many digits. Example: 89001110777",
    "err_phone_invalid": "Enter a valid number. Example: 89001110777",
    "err_birth_date_empty": (
        "Enter date of birth as DD.MM.YYYY (e.g. 15.05.1995)."
    ),
    "err_birth_date_format": (
        "Invalid format. Use DD.MM.YYYY (e.g. 15.05.1995)."
    ),
    "err_birth_date_digits": (
        "Enter date in digits as DD.MM.YYYY (e.g. 15.05.1995)."
    ),
    "err_birth_date_invalid": "Invalid date. Check day, month and year.",
    "err_birth_date_future": "Date of birth cannot be in the future.",
    "err_birth_date_min_age": "Age must be at least {age} years.",
    "err_birth_date_max_age": (
        "Enter a real date of birth (age up to {age} years)."
    ),
    "err_city_required": "Specify city. Enter again:",
    "err_city_from_location": "Could not determine city from location. Enter city manually or try again.",
    "err_city_not_found_use_map": (
        "Could not determine location from the name. "
        "Enter the exact city name or share your location."
    ),
    "err_company_activity_max": "Max {max} characters.",
    "err_nickname_no_url": "Enter name, not an Instagram link.",
    "err_topics_empty": "Enter at least one topic:",
    "err_topics_max": "Enter no more than {max} topics.",
    "err_audience_geo_empty": "Specify at least one city. Enter again:",
    "err_audience_geo_max": "Max {max} characters.",
    "err_price_positive": "Price must be greater than 0.",
    "err_price_max": ("Amount exceeds maximum allowed ({max} {currency})."),
    "msg_what_do_you_need": "What do you need?",
    "msg_choose_from_keyboard": "Choose one of the options on the keyboard.",
    "msg_coop_format": "What cooperation format do you prefer?",
    "msg_enter_number": "Enter a number, e.g. 1500.",
    "msg_how_many_creators": "How many creators do you need?",
    "msg_product_link": "Enter product link (for responding creators):",
    "msg_choose_count": "Choose one of: {counts}.",
    "msg_where_use_ugc": "Where will you use the UGC video?",
    "msg_send_photo": "Send product photo:",
    "msg_order_task_description": (
        "Briefly describe the task for creators.\n"
        "What to shoot and in what format. Example: Unboxing video."
    ),
    "msg_order_budget": (
        "Budget per 1 UGC video? Enter price ({currency}): 500, 1000, 2000"
    ),
    "msg_order_barter_ask": (
        "What do you offer as barter?\n"
        "Brand product (short description) + delivery"
    ),
    "msg_order_photo_intro": (
        "Attach a photo (optional).\n"
        "A photo helps the creator understand the order faster and boosts response."
    ),
    "msg_order_photo_choose": (
        "Choose «Add photo» or «Skip» on the keyboard, or send a product photo."
    ),
    "msg_order_deadline": (
        "When do you need the content? "
        "Specify how many days after agreement you expect the preview."
    ),
    "msg_order_geo": (
        "In which city, region or country can the creator be located? "
        "Specify one option, e.g. London, UK or Worldwide. "
        "Used for barter orders and product delivery."
    ),
    "msg_order_created": (
        "Order created ✅\n\n"
        "We will send your offer to suitable UGC creators after payment.\n\n"
        "🔄 **How it works**\n\n"
        "• Creators receive an offer with fixed terms\n"
        "• Only those ready to work on your terms respond\n"
        "• You will receive responses with links to creator profiles\n"
        "• You initiate contact\n\n"
        "⚠️ **Important**\n\n"
        "• We recommend paying the creator after receiving a watermarked preview\n"
        "• The platform does not participate in negotiations or payments\n"
        "• We cannot guarantee the creator will not change their decision\n"
        "• The creator cannot see your contacts and cannot message first"
    ),
    "msg_profile_empty_creator": "Profile not filled. «Create profile» or /creator",
    "msg_instagram_already_confirmed": "Your Instagram is already verified",
    "msg_instagram_verify_instruction": (
        "<b>To verify your Instagram account, follow 3 steps:</b>\n\n"
        "1. Copy the code below\n"
        "2. Send it in a direct message to the UMC Instagram account\n"
        "3. Wait for automatic verification\n\n"
        '🔗 Instagram UMC: <a href="{url}">{url}</a>\n\n'
        "🔐 Your code (valid for 15 minutes) 👇"
    ),
    "msg_invalid_format": "Invalid format.",
    "msg_invalid_id_format": "Invalid identifier format.",
    "msg_order_not_found_short": "Order not found.",
    "msg_no_bloggers_complain": "No bloggers to complain about.",
    "msg_complain_on": "Complain about {blogger_name}",
    "msg_choose_blogger_complain": "Choose blogger to complain about:",
    "msg_no_access_order": "You don't have access to this order.",
    "msg_choose_complaint_reason": "Choose complaint reason:",
    "msg_complaint_no_bloggers": "No bloggers to complain about.",
    "msg_invalid_user_id": "Invalid user ID.",
    "msg_invalid_reason": "Invalid reason.",
    "msg_data_error": "Data processing error.",
    "msg_describe_complaint": "Describe the complaint:",
    "msg_error_try_later": "An error occurred. Try again later.",
    "msg_enter_complaint_reason": "Please enter the complaint reason.",
    "msg_order_closed": "Order already closed.",
    "msg_order_closed_full": (
        "❗ Order already closed\n\n"
        "Thanks for responding — all creators for this order have been matched.\n\n"
        "We'll send new orders as soon as they appear.\n\n"
        "Watch for notifications in the bot 🙌"
    ),
    "msg_blogger_after_response_what_next": (
        "⏳ What's next\n\n"
        "💬 Wait for the advertiser to message — they have your Instagram link "
        "and will reach out first\n"
        "📩 Check Direct requests\n"
        "👀 Use watermarked previews for demos\n"
        "💸 Get payment after approving the preview\n"
        "🎥 Send final UGC only after payment\n"
        "❗ Refusing after responding may lead to account limits\n"
        "🤝 The platform is not involved in negotiations or payment."
    ),
    "msg_offer_accepted": "Response accepted! Wait for the advertiser to contact you.",
    "msg_offer_order_filled": (
        "The current creator shortlist is closed. We've added you to the waitlist — "
        "if we need a replacement or the advertiser expands the shortlist, "
        "we'll send you an offer first."
    ),
    "msg_offer_order_filled_toast": "Added to waitlist",
    "msg_advertiser_after_payment_success": (
        "Payment successful ✅\n\nCreator matching for your order is now active."
    ),
    "msg_advertiser_after_payment_what_next": (
        "🔄 **What's next**\n\n"
        "📩 Creators receive your offer\n"
        "🔗 You'll get responses with links to their profiles\n"
        "💬 You contact selected creators yourself"
    ),
    "msg_advertiser_after_payment_important": (
        "⚠️ **Important**\n\n"
        "🧷 Don't change offer terms after publishing\n"
        "🔄 If terms change, the creator may decline\n"
        "🤝 The platform is not a party to the deal\n"
        "💸 You pay creators directly\n"
        "👀 Pay after viewing watermarked preview\n"
        "🚫 The platform is not responsible for creators"
    ),
    "msg_phone_request": (
        "Enter phone number for order contact.\n"
        "Tap the button below or enter the number manually (e.g. 89001110777)."
    ),
    "msg_instagram_confirmed": (
        "Instagram verified ✅. Brands can send you offers."
    ),
    "msg_instagram_account_lost": (
        "Your Instagram account has been deleted or changed. "
        "To receive orders, edit your profile "
        "and complete verification again."
    ),
    "msg_instagram_verification_api_unavailable": (
        "We couldn't verify your Instagram account. "
        "Please try verification again later or contact support."
    ),
    "msg_instagram_mismatch": (
        "The Instagram in your profile doesn't match the account "
        "you sent the code from. Open «My profile», edit the blogger profile "
        "and set the correct Instagram."
    ),
    "msg_too_many_requests": "Too many requests. Try again later.",
    "msg_invalid_order_id_short": "Invalid order ID.",
    "msg_order_activated": "Order activated, sent to bloggers.",
    "err_user_not_found": "User not found.",
    "err_blogger_registration": "Blogger registration error.",
    "err_advertiser_registration": "Advertiser registration error.",
    "err_order_not_found": "Order not found.",
    "err_order_not_active": "Order not active.",
    "err_order_creation": "Order creation error.",
    "err_order_already_responded": "You already responded to this order.",
    "err_order_response_limit": "Order response limit reached.",
    "err_order_not_new": "Order not in NEW status.",
    "err_order_not_yours": "Order does not belong to advertiser.",
    "err_order_invalid_id": "Invalid order identifier.",
    "msg_offer_skipped": "OK, skipped.",
    "msg_offer_skip_reason_prompt": "Please select a reason:",
    "btn_reject_low_price": "Low price",
    "btn_reject_wrong_format": "Wrong ad format",
    "btn_reject_uninteresting": "Uninteresting product",
    "btn_reject_no_time": "No time",
    "btn_reject_already_working": "Already working with the brand directly",
    "msg_enter_desired_price": "Enter your desired price:",
    "msg_invalid_price": "Enter a number from {min} to {max} {currency}",
    "msg_offer_skipped_with_reason": "Thanks for feedback. Declined: {reason}. Skipped.",
    "msg_offer_skipped_low_price": "Thanks. Declined: Low price. Desired: {price} {currency}. We may return with a new offer.",
    "msg_manager_low_price_notification": "Blogger {blogger} declined: low price. Wants {desired_price} {currency} (offered: {offer_price} {currency}).\n{product_link}",
    "btn_cancel_price_entry": "Cancel",
    "msg_price_entry_cancelled": "Decline recorded. Skipped.",
    "err_interaction_not_found": "Interaction not found.",
    "err_interaction": "Interaction error.",
    "err_interaction_status": "Interaction not in ISSUE.",
    "err_interaction_resolution": "Invalid status for manual resolution.",
    "err_complaint_exists": "You already filed a complaint for this order.",
    "err_complaint_not_found": "Complaint not found.",
    "err_price_exceeds": "Amount exceeds maximum ({amount} {currency}).",
    "err_generic": "An error occurred: {error}",
    "msg_feedback_thanks": "Thanks, response saved.",
    "msg_feedback_thanks_short": "Thanks for your feedback.",
    "msg_interaction_not_found": "Interaction not found.",
    "msg_insufficient_rights": "Insufficient rights.",
    "msg_feedback_thanks_ok": "Thanks.",
    "msg_describe_problem": (
        "Describe the issue and attach screenshots or other proof."
    ),
    "msg_postpone_max": "Max postponements reached. Status set to 'No deal'.",
    "msg_postpone_72": "Check postponed 72h. Postponements: {cnt}/{max}",
    "msg_session_expired_feedback": "Session expired. Answer the feedback question again.",
    "msg_error_try_again": "Error. Try again.",
    "msg_add_description_or_photo": "Add description or photo, then tap «Send».",
    "msg_add_description_before_send": "Add description or photo before sending.",
    "msg_complaint_error": "Error creating request. Try again or contact support.",
    "msg_complaint_received": "We received your request. Support will look into it.",
    "msg_enter_reason": "Please enter the reason:",
    "msg_enter_reason_text": "Enter reason as text.",
    "msg_nps_thanks": "Thanks for rating!",
    "msg_nps_question": "How likely are you to recommend us? (1–5)",
    "msg_nps_thank": "Thanks! Your feedback matters.",
    "msg_invalid_format_short": "Invalid format.",
    "msg_invalid_id": "Invalid identifier.",
    "msg_score_1_to_5": "Score must be 1 to 5.",
    "msg_invalid_status": "Invalid status.",
    "msg_invalid_response": "Invalid response format.",
    "msg_error_later": "An error occurred. Try again later.",
    "msg_cancelled": "Cancelled.",
    "msg_invalid_uuid": "Invalid user identifier.",
    "msg_user_not_telegram": "User not on Telegram.",
    # Language/country selection
    "language_prompt": "Choose language:",
    "country_prompt": "Select your country:",
    "country_changed": "Country changed.",
    # Offer texts
    "offer_header": "New order",
    "offer_details_header": "📋 Order details:",
    "offer_format": "🎥 Format: {format_label}",
    "offer_task": "📝 Task: {task}",
    "offer_budget": "💰 Budget: {price} {currency} per UGC video",
    "offer_barter": "🎁 Barter: {description}",
    "offer_content_usage": "📢 Usage: {usage}",
    "offer_deadlines": "⏱ Deadlines: {deadlines}",
    "offer_geography": "📍 Geography: {geography}",
    "offer_bloggers_needed": "👥 Creators needed: {count}",
    "offer_warning": (
        "⚠️ Important\n"
        "🧷 Respond only if you are ready to work under the stated conditions\n"
        "❗ Refusing after responding without changed conditions from the advertiser"
        "   may lead to a complaint and account restriction"
    ),
    "offer_how_it_works": (
        "⏳ How it works\n"
        "● You respond to the offer\n"
        "● You receive a product link\n"
        "● The advertiser gets your profile and contacts you first\n"
        "● The platform is not involved in negotiations or payment"
    ),
    "offer_format_label_ugc_placement": "UGC + placement",
    "offer_format_label_ugc_only": "UGC video for brand",
    "btn_offer_accept": "Ready to shoot UGC",
    "btn_offer_skip": "Skip",
    "msg_ugc_video_saved_creator": "✅ Your video has been accepted by the manager and saved.",
    "msg_ugc_video_saved_advertiser": (
        "✅ Creator {telegram} has successfully completed the order!\nVideo link: {url}"
    ),
    # Manager: creator order management
    "msg_creator_removed_from_order": (
        "Unfortunately, you have been removed from the order by the manager."
    ),
    "msg_creator_added_to_order": (
        "You have been added to the order! "
        "Your manager: {manager_telegram}. "
        "We look forward to your video."
    ),
    # Complaint button
    "btn_complaint": "Report {name}",
}
